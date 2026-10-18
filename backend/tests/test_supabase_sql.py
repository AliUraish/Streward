"""The Supabase migrations against a local stand-in Postgres: RLS authority, the append-only hash-chained ledger,
Realtime HUD policies, the inbox queue and the access token hook.

Starts a throwaway cluster (initdb/pg_ctl from PATH or Homebrew) on a free localhost port, applies
supabase/tests/standin.sql (the Supabase roles, auth/realtime/storage objects and default privileges read from the
hosted project) and every migration twice (idempotency), then exercises the policies as each agent the way PostgREST
does: SET ROLE authenticated plus request.jwt.claims. Skipped when no Postgres binaries are installed.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.mirror import build_row
from src.signing import canonical_json
from src.supa_authority import AGENT_IDS, MATRIX, permitted

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("000[2-9]_*.sql"))


def _bin(name):
    found = shutil.which(name) or next((str(p) for p in (Path("/opt/homebrew/bin") / name, Path("/usr/local/bin") / name,
                                                        Path("/opt/homebrew/opt/postgresql@16/bin") / name) if p.exists()), None)
    return found


PG = {name: _bin(name) for name in ("initdb", "pg_ctl", "psql")}
pytestmark = pytest.mark.skipif(not all(PG.values()), reason="local Postgres binaries (initdb, pg_ctl, psql) not installed")


class Pg:
    def __init__(self, port):
        self.port = port
        self.users = {}

    def run(self, script: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run([PG["psql"], "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-d", "postgres", "-X", "-q", "-At",
                                 "-v", "ON_ERROR_STOP=1"], input=script, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise AssertionError(result.stderr)
        return result

    def file(self, path: Path):
        result = subprocess.run([PG["psql"], "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-d", "postgres", "-X", "-q",
                                 "-v", "ON_ERROR_STOP=1", "-f", str(path)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"

    def claims(self, agent: str | None, role: str = "authenticated") -> dict:
        if agent is None:
            return {"role": role}
        return {"sub": self.users[agent], "role": "authenticated", "agent_id": agent}

    def as_(self, sql: str, agent: str | None = None, role: str = "authenticated", topic: str | None = None, check: bool = False):
        """Run `sql` the way PostgREST would for this caller; returns (ok, stdout, stderr)."""
        claims = json.dumps(self.claims(agent, role)).replace("'", "''")
        db_role = "authenticated" if agent else role
        script = (f"begin;\nset local role {db_role};\nset local request.jwt.claims = '{claims}';\n"
                  + (f"set local realtime.topic = '{topic}';\n" if topic else "") + sql.rstrip().rstrip(";") + ";\ncommit;\n")
        result = self.run(script, check=check)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()

    def value(self, sql: str, agent: str | None = None, role: str = "authenticated", topic: str | None = None):
        ok, out, err = self.as_(sql, agent, role, topic)
        assert ok, err
        return out


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    base = tmp_path_factory.mktemp("pg")
    data = base / "data"
    subprocess.run([PG["initdb"], "-D", str(data), "-U", "postgres", "--auth=trust", "-E", "UTF8", "--locale=C"], check=True,
                   capture_output=True, timeout=120)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    subprocess.run([PG["pg_ctl"], "-D", str(data), "-o", f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''",
                    "-l", str(base / "log.txt"), "-w", "start"], check=True, capture_output=True, timeout=120)
    db = Pg(port)
    try:
        db.file(ROOT / "supabase" / "tests" / "standin.sql")
        for _ in range(2):  # every migration is idempotent
            for migration in MIGRATIONS:
                db.file(migration)
        for agent in AGENT_IDS:
            user = str(uuid.uuid4())
            db.users[agent] = user
            db.run(f"insert into auth.users (id, email) values ('{user}', 'agent+{agent}@steward.invalid');"
                   f"update public.agents set auth_user_id = '{user}' where id = '{agent}';")
        yield db
    finally:
        subprocess.run([PG["pg_ctl"], "-D", str(data), "-m", "immediate", "-w", "stop"], capture_output=True, timeout=60)


# ---- helpers ------------------------------------------------------------------------------------------------------------

KEY = Ed25519PrivateKey.generate()
PUBLIC = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def attestation(site="myer-plant", value=3.4, **extra):
    record = dict(id="att-" + uuid.uuid4().hex[:16], propertyId=site, assetTag="P-101", componentId="pump-01", attribute="pressure_bar", value=value,
                  unit="bar", observedAt="2026-10-18T05:00:00.123456Z", evidenceHashes=["ab" * 32], checks=[dict(name="tag", passed=True, reason="ok")],
                  verdict="accepted", source=dict(kind="human", ref="sms:msg-1"), verifierVersion="steward-verify/1", signedAt="2026-10-18T05:00:01Z",
                  publicKey=PUBLIC, **extra)
    record["signature"] = base64.b64encode(KEY.sign(canonical_json(record))).decode()
    return record


def insert_sql(table: str, row: dict) -> str:
    payload = json.dumps(row).replace("'", "''")
    return f"insert into public.{table} select * from jsonb_populate_record(null::public.{table}, '{payload}'::jsonb)"


# ---- tests --------------------------------------------------------------------------------------------------------------

def test_matrix_in_postgres_is_the_backend_matrix(pg):
    rows = json.loads(pg.run("select json_agg(row_to_json(a)) from steward.authority a").stdout)
    sql = {r["tbl"]: dict(site_col=r["site_col"], site_kind=r["site_kind"], writers=tuple(r["writers"]), bind=r["bind_col"], append_only=r["append_only"])
           for r in rows}
    assert sql == MATRIX


def test_every_table_has_rls_and_no_anon_writes(pg):
    rows = json.loads(pg.run("select json_agg(json_build_object('t', c.relname, 'rls', c.relrowsecurity)) from pg_class c "
                             "join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'r'").stdout)
    assert rows and all(r["rls"] for r in rows), rows
    grants = pg.run("select string_agg(table_name || ':' || privilege_type, ',') from information_schema.role_table_grants "
                    "where table_schema = 'public' and grantee = 'anon'").stdout.strip()
    assert sorted(grants.split(",")) == sorted(f"{t}:SELECT" for t in ("eye_frames", "facts", "findings", "maintenance_windows"))


def test_probe_matches_python_authority_for_every_agent_and_table(pg):
    mismatches = []
    for table, spec in MATRIX.items():
        for agent in AGENT_IDS:
            result = json.loads(pg.value(f"select public.steward_authority_probe('{table}', 'insert', 'myer-plant')", agent))
            sample = {spec["site_col"]: ["myer-plant"] if spec["site_kind"] == "many" else "myer-plant"} if spec["site_col"] else {}
            if spec["bind"]:
                sample[spec["bind"]] = agent
            expected = permitted(agent, table, sample) and table != "facts"  # the probe fact cites no ledger attestation
            if bool(result.get("allowed")) != expected:
                mismatches.append((table, agent, result))
    assert not mismatches, mismatches


def test_technician_attestation_is_refused_by_rls(pg):
    result = json.loads(pg.value("select public.steward_authority_probe('attestations', 'insert', 'myer-plant')", "myer-technician"))
    assert result == dict(attempted=True, allowed=False, sqlstate="42501", detail=None, hint=None, rolledBack=True,
                          message='new row violates row-level security policy for table "attestations"')
    row = build_row("attestation", attestation())
    ok, _, err = pg.as_(insert_sql("attestations", row), "myer-technician")
    assert not ok and "row-level security" in err


def test_engineer_writes_signed_attestations_for_its_own_site_only(pg):
    record = attestation()
    row = build_row("attestation", record)
    assert row["signed_payload"]
    ok, _, err = pg.as_(insert_sql("attestations", row), "myer-engineer")
    assert ok, err
    assert pg.run(f"select written_by from public.attestations where id = '{record['id']}'").stdout.strip() == "myer-engineer"
    other = build_row("attestation", attestation(site="bristol-pumps"))
    ok, _, err = pg.as_(insert_sql("attestations", other), "myer-engineer")
    assert not ok and "row-level security" in err  # cross-site write refused
    unsigned = dict(build_row("attestation", attestation()), signed_payload=None)
    ok, _, err = pg.as_(insert_sql("attestations", unsigned), "myer-engineer")
    assert not ok and "row-level security" in err  # agents must send the signed payload
    forged = build_row("attestation", attestation())
    forged["value"] = 9.9  # the column no longer matches what was signed
    ok, _, err = pg.as_(insert_sql("attestations", forged), "myer-engineer")
    assert not ok and "signed_payload does not match column value" in err
    # a fact must cite an attestation already in the ledger
    fact = dict(id="fact-" + uuid.uuid4().hex[:8], property_id="myer-plant", asset_tag="P-101", attribute="pressure_bar", value=3.4,
                attestation_id=record["id"], observed_at="2026-10-18T05:00:00Z")
    ok, _, err = pg.as_(insert_sql("facts", fact), "myer-engineer")
    assert ok, err
    ok, _, err = pg.as_(insert_sql("facts", dict(fact, id="fact-x", attestation_id="att-missing")), "myer-engineer")
    assert not ok and "row-level security" in err


def test_untrusted_signing_key_is_refused_once_a_key_is_trusted(pg):
    pg.run(f"select public.steward_trust_signing_key('{PUBLIC}', 'test backend')")
    try:
        stranger = Ed25519PrivateKey.generate()
        record = attestation()
        record["publicKey"] = base64.b64encode(stranger.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        record.pop("signature")
        record["signature"] = base64.b64encode(stranger.sign(canonical_json(record))).decode()
        ok, _, err = pg.as_(insert_sql("attestations", build_row("attestation", record)), "myer-engineer")
        assert not ok and "not a trusted Steward signing key" in err
    finally:
        pg.run("delete from steward.signing_keys")


def test_compliance_writes_obligations_for_its_site_and_nobody_else_does(pg):
    obligation = dict(id="obl-" + uuid.uuid4().hex[:8], site_id="bristol-pumps", title="PSSR written scheme", status="ok")
    ok, _, err = pg.as_(insert_sql("obligations", obligation), "bristol-compliance")
    assert ok, err
    for agent in ("myer-compliance", "bristol-engineer", "bristol-technician", "director", "operator"):
        ok, _, err = pg.as_(insert_sql("obligations", dict(obligation, id="obl-" + uuid.uuid4().hex[:8])), agent)
        assert not ok and "row-level security" in err, agent


def test_reads_are_scoped_by_site(pg):
    pg.run(insert_sql("issues", dict(id="iss-my", site_id="myer-plant", summary="m")) + ";" + insert_sql("issues", dict(id="iss-br", site_id="bristol-pumps", summary="b")))
    assert pg.value("select string_agg(id, ',' order by id) from public.issues where id like 'iss-%'", "myer-manager") == "iss-my"
    assert pg.value("select string_agg(id, ',' order by id) from public.issues where id like 'iss-%'", "bristol-technician") == "iss-br"
    assert pg.value("select string_agg(id, ',' order by id) from public.issues where id like 'iss-%'", "director") == "iss-br,iss-my"


def test_telemetry_rows_are_bound_to_their_author(pg):
    row = dict(id="tel-" + uuid.uuid4().hex[:8], agent_id="myer-engineer", site_id="myer-plant", kind="tool", tool="eye_look", tokens=10, ok=True)
    ok, _, err = pg.as_(insert_sql("telemetry", row), "myer-manager")
    assert not ok and "row-level security" in err
    ok, _, err = pg.as_(insert_sql("telemetry", row), "myer-engineer")
    assert ok, err


def test_attestations_are_append_only_for_every_role(pg):
    record = attestation()
    pg.run(insert_sql("attestations", build_row("attestation", record)))  # postgres (owner)
    for role in ("service_role", "authenticated", "anon"):
        ok, _, err = pg.as_(f"update public.attestations set verdict = 'rejected' where id = '{record['id']}'", None if role != "authenticated" else "myer-engineer", role)
        assert not ok and "permission denied" in err, role
        ok, _, err = pg.as_(f"delete from public.attestations where id = '{record['id']}'", None if role != "authenticated" else "myer-engineer", role)
        assert not ok and "permission denied" in err, role
    result = pg.run(f"update public.attestations set verdict = 'rejected' where id = '{record['id']}'", check=False)
    assert result.returncode != 0 and "append-only" in result.stderr  # even the table owner hits the trigger
    result = pg.run("truncate public.attestations", check=False)
    assert result.returncode != 0 and "append-only" in result.stderr


def test_ledger_chain_verifies_and_reports_the_first_broken_link(pg):
    for _ in range(3):
        pg.run(insert_sql("attestations", build_row("attestation", attestation())))
    result = json.loads(pg.value("select public.verify_ledger()", "director"))
    assert result["ok"] is True and result["checked"] >= 3 and result["head"]["chainSeq"] == result["checked"]
    head = result["head"]
    tail = json.loads(pg.value(f"select public.verify_ledger({head['chainSeq'] + 1}, '{head['rowHash']}')", None, "service_role"))
    assert tail == dict(ok=True, checked=0, fromSeq=head["chainSeq"] + 1, head=None, signatures=tail["signatures"])
    victim = pg.run("select id from public.attestations order by chain_seq offset 1 limit 1").stdout.strip()
    pg.run("alter table public.attestations disable trigger steward_00_append_only;"
           f"update public.attestations set value = '99'::jsonb where id = '{victim}';"
           "alter table public.attestations enable trigger steward_00_append_only;")
    broken = json.loads(pg.value("select public.verify_ledger()", None, "service_role"))
    assert broken["ok"] is False and broken["brokenAt"]["id"] == victim and "does not match its row_hash" in broken["brokenAt"]["reason"]
    assert pg.as_("select public.verify_ledger()", None, "anon")[0] is False  # anon may not run the verifier


def test_anon_reads_only_the_public_tables(pg):
    for table in ("crew_members", "telemetry", "memories", "conversations", "notifications", "attestations", "changes", "issues", "agents"):
        ok, _, err = pg.as_(f"select count(*) from public.{table}", None, "anon")
        assert not ok and "permission denied" in err, table
    for table in ("facts", "eye_frames", "findings", "maintenance_windows"):
        assert pg.as_(f"select count(*) from public.{table}", None, "anon")[0], table
    ok, _, err = pg.as_(insert_sql("facts", dict(id="fact-anon", property_id="myer-plant")), None, "anon")
    assert not ok and "permission denied" in err


def test_realtime_hud_policies(pg):
    pg.run("insert into realtime.messages (topic, extension, event, payload, private) values ('site:myer-plant:hud', 'broadcast', 'hud', '{}', true)")
    assert pg.value("select count(*) from realtime.messages", None, "anon", topic="site:myer-plant:hud") == "1"
    assert pg.value("select count(*) from realtime.messages", None, "anon", topic="site:evil-site:hud") == "0"
    assert pg.value("select count(*) from realtime.messages", None, "anon", topic="private-room") == "0"
    presence = "insert into realtime.messages (topic, extension, event, payload, private) values ('site:myer-plant:hud', '{ext}', 'x', '{{}}', true)"
    assert pg.as_(presence.format(ext="presence"), None, "anon", topic="site:myer-plant:hud")[0]
    ok, _, err = pg.as_(presence.format(ext="broadcast"), None, "anon", topic="site:myer-plant:hud")
    assert not ok and "row-level security" in err  # no browser can send a HUD event
    ok, _, err = pg.as_(presence.format(ext="broadcast"), "myer-engineer", topic="site:myer-plant:hud")
    assert not ok and "row-level security" in err  # not even a signed-in agent


def test_inbox_queue_dedupes_counts_and_drains(pg):
    message = json.dumps(dict(rawB64=base64.b64encode(b'{"id":"evt-1"}').decode(), headers={"x-inkbox-signature": "sha256=00"}))
    first = json.loads(pg.value(f"select public.inkbox_enqueue('evt-1', 'req-1', 'text.received', '{message}'::jsonb)", None, "service_role"))
    again = json.loads(pg.value(f"select public.inkbox_enqueue('evt-1', 'req-2', 'text.received', '{message}'::jsonb)", None, "service_role"))
    assert first["accepted"] and first["duplicate"] is False and again["duplicate"] is True
    rows = pg.value("select json_agg(r) from public.inkbox_inbox_read(10, 30) r", None, "service_role")
    read = json.loads(rows)
    assert len(read) == 1 and read[0]["message"]["rawB64"]
    assert pg.value(f"select public.inkbox_inbox_archive({read[0]['msg_id']})", None, "service_role") == "t"
    stats = json.loads(pg.value("select public.inkbox_inbox_stats()", None, "service_role"))
    assert stats["queued"] == 0 and stats["archived"] == 1 and stats["callsToday"] == 2
    pg.run("select public.steward_put_setting('edge_calls_day_cap', '2')")
    refused = json.loads(pg.value(f"select public.inkbox_enqueue('evt-2', 'req-3', 'text.received', '{message}'::jsonb)", None, "service_role"))
    assert refused["accepted"] is False and "cap" in refused["reason"]
    pg.run("select public.steward_put_setting('edge_calls_day_cap', '5000')")
    for role in ("anon", "authenticated"):
        assert not pg.as_("select public.inkbox_inbox_read(1, 30)", "myer-engineer" if role == "authenticated" else None, role)[0]


def test_access_token_hook_adds_agent_claims(pg):
    user = pg.users["bristol-compliance"]
    event = json.dumps(dict(user_id=user, claims=dict(sub=user, role="authenticated", aal="aal1"), authentication_method="password"))
    script = f"set role supabase_auth_admin; select steward.custom_access_token_hook('{event}'::jsonb);"
    claims = json.loads(pg.run(script).stdout.strip())["claims"]
    assert claims["agent_id"] == "bristol-compliance" and claims["agent_level"] == 4 and claims["site_id"] == "bristol-pumps"
    assert claims["agent_role"] == "compliance" and claims["aal"] == "aal1"
    stranger = json.dumps(dict(user_id=str(uuid.uuid4()), claims=dict(role="authenticated", agent_id="operator")))
    claims = json.loads(pg.run(f"set role supabase_auth_admin; select steward.custom_access_token_hook('{stranger}'::jsonb);").stdout.strip())["claims"]
    assert "agent_id" not in claims  # a user without an agent row gets no agent claims, whatever it presents
    ok, _, err = pg.as_(f"select steward.custom_access_token_hook('{event}'::jsonb)", "operator")
    assert not ok and "permission denied" in err


def test_claim_must_match_the_signed_in_user(pg):
    """A JWT whose agent_id claim disagrees with its user's agent row gets no authority at all."""
    claims = json.dumps({"sub": pg.users["myer-technician"], "role": "authenticated", "agent_id": "myer-engineer"})
    script = (f"begin; set local role authenticated; set local request.jwt.claims = '{claims}'; "
              "select coalesce(steward.agent_role(), 'none'); commit;")
    assert pg.run(script).stdout.strip() == "none"


def test_third_site_needs_no_policy_change(pg):
    """tomioka-mill (contract 5) works through the same site-agnostic policies: its team is scoped to it, the director
    covers it, and its HUD topic is authorised because its agents exist."""
    record = attestation(site="tomioka-mill")
    ok, _, err = pg.as_(insert_sql("attestations", build_row("attestation", record)), "tomioka-engineer")
    assert ok, err
    ok, _, err = pg.as_(insert_sql("attestations", build_row("attestation", attestation(site="myer-plant"))), "tomioka-engineer")
    assert not ok and "row-level security" in err
    assert json.loads(pg.value("select public.steward_authority_probe('attestations', 'insert', 'tomioka-mill')", "tomioka-technician"))["allowed"] is False
    pg.run(insert_sql("issues", dict(id="iss-tm", site_id="tomioka-mill", summary="humidity 88 %")))
    assert pg.value("select count(*) from public.issues where id = 'iss-tm'", "director") == "1"
    assert pg.value("select count(*) from public.issues where id = 'iss-tm'", "bristol-manager") == "0"
    pg.run("insert into realtime.messages (topic, extension, event, payload, private) values ('site:tomioka-mill:hud', 'broadcast', 'hud', '{}', true)")
    assert pg.value("select count(*) from realtime.messages where topic = 'site:tomioka-mill:hud'", None, "anon", topic="site:tomioka-mill:hud") == "1"
