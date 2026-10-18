-- 0004_ledger.sql: the attestation ledger is append-only, hash-chained and (with pgsodium) signature-checked. Idempotent.
--
--   * BEFORE UPDATE OR DELETE / BEFORE TRUNCATE triggers raise for every role, and UPDATE, DELETE and TRUNCATE are
--     revoked from anon, authenticated and service_role: no API key can change or remove a signed attestation.
--   * A BEFORE INSERT trigger takes an advisory lock and sets chain_seq, prev_hash and
--     row_hash = sha256(prev_hash || canonical payload) with pgcrypto, so any later edit breaks the chain.
--   * When the row carries signed_payload (the exact canonical JSON the backend signed), a BEFORE INSERT trigger checks
--     that it matches the row's columns, that public_key is a trusted Steward key (steward.signing_keys), and, when
--     pgsodium is installed, that the Ed25519 signature verifies (pgsodium.crypto_sign_verify_detached). RLS (0003)
--     requires signed_payload on every agent insert, so a forged attestation is refused by the database itself.
--   * public.verify_ledger() walks the chain and returns ok or the first broken link.

do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pgsodium') then
    create extension if not exists pgsodium;
  end if;
end $$;

-- Trusted Ed25519 public keys (base64, as the backend publishes them at GET /api/attestations/public-key).
create table if not exists steward.signing_keys (
  public_key text primary key,
  label      text,
  added_at   timestamptz not null default now()
);
revoke all on steward.signing_keys from public, anon, authenticated;
grant select on steward.signing_keys to service_role;

create or replace function public.steward_trust_signing_key(p_public_key text, p_label text default 'steward backend')
returns boolean
language sql
security definer
set search_path = ''
as $$
  insert into steward.signing_keys (public_key, label) values (p_public_key, p_label)
  on conflict (public_key) do update set label = excluded.label
  returning true
$$;
revoke all on function public.steward_trust_signing_key(text, text) from public, anon, authenticated;
grant execute on function public.steward_trust_signing_key(text, text) to service_role;

-- ---------------------------------------------------------------------------------------------------------------
-- Canonical payload and checks
-- ---------------------------------------------------------------------------------------------------------------
create or replace function steward.ts(t timestamptz) returns text
language sql stable set search_path = ''
as $$ select to_char(t at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') $$;

-- jsonb text output is canonical (keys ordered, no insignificant whitespace); timestamps are pinned to UTC microseconds.
create or replace function steward.attestation_canonical(a public.attestations) returns text
language sql stable set search_path = ''
as $$
  select jsonb_build_object(
    'chain_seq', a.chain_seq, 'id', a.id, 'property_id', a.property_id, 'asset_tag', a.asset_tag,
    'component_id', a.component_id, 'attribute', a.attribute, 'value', a.value, 'unit', a.unit,
    'observed_at', steward.ts(a.observed_at), 'evidence_hashes', a.evidence_hashes, 'checks', a.checks,
    'verdict', a.verdict, 'source', a.source, 'verifier_version', a.verifier_version,
    'signed_at', steward.ts(a.signed_at), 'public_key', a.public_key, 'signature', a.signature,
    'signed_payload', a.signed_payload, 'written_by', a.written_by)::text
$$;

create or replace function steward.attestation_hash(a public.attestations) returns text
language sql stable set search_path = ''
as $$ select encode(extensions.digest(convert_to(coalesce(a.prev_hash, '') || steward.attestation_canonical(a), 'UTF8'), 'sha256'), 'hex') $$;

create or replace function steward.sodium_available() returns boolean
language sql stable set search_path = ''
as $$ select to_regprocedure('pgsodium.crypto_sign_verify_detached(bytea,bytea,bytea)') is not null $$;

create or replace function steward.signature_valid(a public.attestations) returns boolean
language plpgsql stable security definer set search_path = ''
as $$
begin
  if a.signed_payload is null or a.signature is null or a.public_key is null then
    return null;
  end if;
  return pgsodium.crypto_sign_verify_detached(decode(a.signature, 'base64'), convert_to(a.signed_payload, 'UTF8'), decode(a.public_key, 'base64'));
exception
  when others then
    return false;
end
$$;

-- Returns null when signed_payload matches every signed column, else the name of the first field that differs.
create or replace function steward.payload_mismatch(a public.attestations) returns text
language plpgsql stable set search_path = ''
as $$
declare
  d jsonb;
begin
  begin
    d := a.signed_payload::jsonb;
  exception
    when others then
      return 'signed_payload (not JSON)';
  end;
  if d ->> 'id' is distinct from a.id then return 'id'; end if;
  if d ->> 'propertyId' is distinct from a.property_id then return 'propertyId'; end if;
  if d ->> 'assetTag' is distinct from a.asset_tag then return 'assetTag'; end if;
  if d ->> 'componentId' is distinct from a.component_id then return 'componentId'; end if;
  if d ->> 'attribute' is distinct from a.attribute then return 'attribute'; end if;
  if coalesce(d -> 'value', 'null'::jsonb) is distinct from coalesce(a.value, 'null'::jsonb) then return 'value'; end if;
  if d ->> 'unit' is distinct from a.unit then return 'unit'; end if;
  if (d ->> 'observedAt')::timestamptz is distinct from a.observed_at then return 'observedAt'; end if;
  if coalesce(d -> 'evidenceHashes', 'null'::jsonb) is distinct from coalesce(a.evidence_hashes, 'null'::jsonb) then return 'evidenceHashes'; end if;
  if coalesce(d -> 'checks', 'null'::jsonb) is distinct from coalesce(a.checks, 'null'::jsonb) then return 'checks'; end if;
  if d ->> 'verdict' is distinct from a.verdict then return 'verdict'; end if;
  if coalesce(d -> 'source', 'null'::jsonb) is distinct from coalesce(a.source, 'null'::jsonb) then return 'source'; end if;
  if d ->> 'verifierVersion' is distinct from a.verifier_version then return 'verifierVersion'; end if;
  if (d ->> 'signedAt')::timestamptz is distinct from a.signed_at then return 'signedAt'; end if;
  if d ->> 'publicKey' is distinct from a.public_key then return 'publicKey'; end if;
  return null;
exception
  when others then
    return 'signed_payload (unreadable field)';
end
$$;

-- ---------------------------------------------------------------------------------------------------------------
-- Triggers (fire in name order: 00 append-only, 10 stamp from 0002, 20 verify, 30 chain)
-- ---------------------------------------------------------------------------------------------------------------
create or replace function steward.refuse_change() returns trigger
language plpgsql set search_path = ''
as $$
begin
  raise exception 'attestations are append-only: % refused for role %', tg_op, current_user
    using errcode = '42501', hint = 'Signed attestations are never changed or removed; append a new attestation instead.';
end
$$;

create or replace function steward.attestations_verify() returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
  v_field text;
begin
  if new.signed_payload is null then
    return new;  -- system rows written before signed payloads existed; RLS demands signed_payload from every agent
  end if;
  v_field := steward.payload_mismatch(new);
  if v_field is not null then
    raise exception 'attestation % refused: signed_payload does not match column %', new.id, v_field using errcode = '22023';
  end if;
  if exists (select 1 from steward.signing_keys) and not exists (select 1 from steward.signing_keys k where k.public_key = new.public_key) then
    raise exception 'attestation % refused: public key is not a trusted Steward signing key', new.id using errcode = '42501';
  end if;
  if steward.sodium_available() and not coalesce(steward.signature_valid(new), false) then
    raise exception 'attestation % refused: the Ed25519 signature does not verify', new.id using errcode = '42501';
  end if;
  return new;
end
$$;

create or replace function steward.attestations_chain() returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
  v_seq  bigint;
  v_prev text;
begin
  -- Serialise appends: one chain, no forks. Volatile, so the head read below sees every committed append.
  perform pg_advisory_xact_lock(hashtextextended('steward.attestations.chain', 0));
  select a.chain_seq, a.row_hash into v_seq, v_prev
  from public.attestations a where a.chain_seq is not null order by a.chain_seq desc limit 1;
  new.chain_seq := coalesce(v_seq, 0) + 1;
  new.prev_hash := coalesce(v_prev, repeat('0', 64));
  new.row_hash := steward.attestation_hash(new);
  return new;
end
$$;

drop trigger if exists steward_00_append_only on public.attestations;
create trigger steward_00_append_only before update or delete on public.attestations
  for each row execute function steward.refuse_change();
drop trigger if exists steward_00_no_truncate on public.attestations;
create trigger steward_00_no_truncate before truncate on public.attestations
  for each statement execute function steward.refuse_change();
drop trigger if exists steward_20_verify on public.attestations;
create trigger steward_20_verify before insert on public.attestations
  for each row execute function steward.attestations_verify();
drop trigger if exists steward_30_chain on public.attestations;
create trigger steward_30_chain before insert on public.attestations
  for each row execute function steward.attestations_chain();

revoke update, delete, truncate on public.attestations from public, anon, authenticated, service_role;

-- ---------------------------------------------------------------------------------------------------------------
-- verify_ledger(): ok, or the first broken link. p_from_seq/p_expected_prev verify incrementally from an anchor.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function public.verify_ledger(p_from_seq bigint default 1, p_expected_prev text default null)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  r          public.attestations;
  v_prev     text;
  v_expected text;
  v_n        bigint := 0;
  v_signed   bigint := 0;
  v_unsigned bigint := 0;
  v_sodium   boolean := steward.sodium_available();
  v_last_seq bigint;
  v_last_id  text;
  v_first    boolean := true;
begin
  if p_from_seq is null or p_from_seq < 1 then
    p_from_seq := 1;
  end if;
  if p_from_seq = 1 then
    v_prev := repeat('0', 64);
  elsif p_expected_prev is not null then
    v_prev := p_expected_prev;
  else
    select a.row_hash into v_prev from public.attestations a where a.chain_seq = p_from_seq - 1;
  end if;
  for r in select * from public.attestations a where a.chain_seq >= p_from_seq order by a.chain_seq loop
    v_n := v_n + 1;
    if v_first and p_from_seq > 1 and r.chain_seq <> p_from_seq then
      return jsonb_build_object('ok', false, 'checked', v_n, 'fromSeq', p_from_seq, 'brokenAt', jsonb_build_object(
        'chainSeq', r.chain_seq, 'id', r.id, 'reason', 'a chain position is missing (row removed)', 'expectedSeq', p_from_seq));
    end if;
    if not v_first and r.chain_seq <> v_last_seq + 1 then
      return jsonb_build_object('ok', false, 'checked', v_n, 'fromSeq', p_from_seq, 'brokenAt', jsonb_build_object(
        'chainSeq', r.chain_seq, 'id', r.id, 'reason', 'a chain position is missing (row removed)', 'expectedSeq', v_last_seq + 1));
    end if;
    if r.prev_hash is distinct from v_prev then
      return jsonb_build_object('ok', false, 'checked', v_n, 'fromSeq', p_from_seq, 'brokenAt', jsonb_build_object(
        'chainSeq', r.chain_seq, 'id', r.id, 'reason', 'prev_hash does not match the previous row_hash', 'expected', v_prev, 'found', r.prev_hash));
    end if;
    v_expected := steward.attestation_hash(r);
    if r.row_hash is distinct from v_expected then
      return jsonb_build_object('ok', false, 'checked', v_n, 'fromSeq', p_from_seq, 'brokenAt', jsonb_build_object(
        'chainSeq', r.chain_seq, 'id', r.id, 'reason', 'row content does not match its row_hash (edited after it was written)',
        'expected', v_expected, 'found', r.row_hash));
    end if;
    if r.signed_payload is null then
      v_unsigned := v_unsigned + 1;
    elsif v_sodium then
      if steward.payload_mismatch(r) is not null or not coalesce(steward.signature_valid(r), false) then
        return jsonb_build_object('ok', false, 'checked', v_n, 'fromSeq', p_from_seq, 'brokenAt', jsonb_build_object(
          'chainSeq', r.chain_seq, 'id', r.id, 'reason', 'the Ed25519 signature does not verify against signed_payload'));
      end if;
      v_signed := v_signed + 1;
    end if;
    v_prev := r.row_hash;
    v_last_seq := r.chain_seq;
    v_last_id := r.id;
    v_first := false;
  end loop;
  return jsonb_build_object('ok', true, 'checked', v_n, 'fromSeq', p_from_seq,
    'head', case when v_last_seq is null then null else jsonb_build_object('chainSeq', v_last_seq, 'rowHash', v_prev, 'id', v_last_id) end,
    'signatures', jsonb_build_object('checked', v_signed, 'unsignedSystemRows', v_unsigned,
                                     'method', case when v_sodium then 'pgsodium.crypto_sign_verify_detached (Ed25519)' else 'unavailable: hash chain only' end));
end
$$;

create or replace function public.steward_ledger_head() returns jsonb
language sql stable security definer set search_path = ''
as $$
  select coalesce((select jsonb_build_object('chainSeq', a.chain_seq, 'rowHash', a.row_hash, 'id', a.id)
                   from public.attestations a where a.chain_seq is not null order by a.chain_seq desc limit 1), 'null'::jsonb)
$$;

revoke all on function public.verify_ledger(bigint, text) from public, anon;
grant execute on function public.verify_ledger(bigint, text) to authenticated, service_role;
revoke all on function public.steward_ledger_head() from public, anon;
grant execute on function public.steward_ledger_head() to authenticated, service_role;

-- Functions in the steward schema are internal: nobody but their owner and explicit grants may call them.
revoke execute on all functions in schema steward from public, anon;
alter default privileges in schema steward revoke execute on functions from public;
grant execute on function steward.agent_id(), steward.agent_role(), steward.agent_site(), steward.agent_is_global() to authenticated, service_role;
grant execute on function steward.custom_access_token_hook(jsonb) to supabase_auth_admin;
