-- 0002_steward.sql: the Steward mirror schema (supersedes 0001_reality.sql). Idempotent: safe to re-run, and it
-- converges a database that already ran 0001 to the same shape.
--
-- Every table and column the backend mirror emits (backend/SUPABASE-COLUMNS.md, src/mirror.py COLUMNS) exists here,
-- all nullable except `id text primary key`, plus:
--   * written_by / mirrored_at on every mirrored table, stamped by a trigger from the caller's JWT (the agent id for
--     agent tokens, `service_role` for the secret key), so the writer of a row can never be spoofed by the payload;
--   * public.agents: the agents of REALITY-CONTRACT-4.md section 1 and REALITY-CONTRACT-5.md section 2 (14), one Auth user each;
--   * signed_payload, chain_seq, prev_hash and row_hash on attestations (filled by 0004_ledger.sql triggers).
-- Secure by default: RLS is enabled on every table and anon/authenticated hold no privileges until 0003_authority.sql
-- grants the exact ones. SQLite in the backend stays the source of truth.

create schema if not exists steward;
comment on schema steward is 'Steward internals (not exposed through the Data API): helpers, triggers, ledger and queue state.';
revoke all on schema steward from public, anon, authenticated;
grant usage on schema steward to service_role;

-- The contract-3 draft table was replaced by conversations of kind 'meeting'.
drop table if exists public.board_meetings;

-- ---------------------------------------------------------------------------------------------------------------
-- Mirrored tables (generated from src/mirror.py COLUMNS; types per backend/SUPABASE-COLUMNS.md)
-- ---------------------------------------------------------------------------------------------------------------
-- facts
create table if not exists public.facts (id text primary key);
alter table public.facts
  add column if not exists "property_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "component_id" text,
  add column if not exists "attribute" text,
  add column if not exists "attribute_class" text,
  add column if not exists "value" jsonb,
  add column if not exists "unit" text,
  add column if not exists "observed_at" timestamptz,
  add column if not exists "ttl_seconds" integer,
  add column if not exists "expires_at" timestamptz,
  add column if not exists "source" jsonb,
  add column if not exists "attestation_id" text,
  add column if not exists "version" bigint,
  add column if not exists "created_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- attestations
create table if not exists public.attestations (id text primary key);
alter table public.attestations
  add column if not exists "property_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "component_id" text,
  add column if not exists "attribute" text,
  add column if not exists "value" jsonb,
  add column if not exists "unit" text,
  add column if not exists "observed_at" timestamptz,
  add column if not exists "evidence_hashes" jsonb,
  add column if not exists "checks" jsonb,
  add column if not exists "verdict" text,
  add column if not exists "source" jsonb,
  add column if not exists "verifier_version" text,
  add column if not exists "signed_at" timestamptz,
  add column if not exists "public_key" text,
  add column if not exists "signature" text,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- work_items
create table if not exists public.work_items (id text primary key);
alter table public.work_items
  add column if not exists "property_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "component_id" text,
  add column if not exists "attribute" text,
  add column if not exists "attribute_class" text,
  add column if not exists "reference" text,
  add column if not exists "state" text,
  add column if not exists "requester" text,
  add column if not exists "budget" numeric,
  add column if not exists "deadline_at" timestamptz,
  add column if not exists "dispatches" jsonb,
  add column if not exists "verdicts" jsonb,
  add column if not exists "fact_id" text,
  add column if not exists "attestation_id" text,
  add column if not exists "receipt" jsonb,
  add column if not exists "escalation_level" integer,
  add column if not exists "created_at" timestamptz,
  add column if not exists "updated_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- dispatches
create table if not exists public.dispatches (id text primary key);
alter table public.dispatches
  add column if not exists "channel" text,
  add column if not exists "to" text,
  add column if not exists "reference" text,
  add column if not exists "sent_at" timestamptz,
  add column if not exists "provider_ref" text,
  add column if not exists "body" text,
  add column if not exists "work_item_id" text,
  add column if not exists "property_id" text,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- changes
create table if not exists public.changes (id text primary key);
alter table public.changes
  add column if not exists "version" bigint,
  add column if not exists "type" text,
  add column if not exists "property_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "ref_id" text,
  add column if not exists "summary" text,
  add column if not exists "at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- subscriptions
create table if not exists public.subscriptions (id text primary key);
alter table public.subscriptions
  add column if not exists "property_id" text,
  add column if not exists "callback_url" text,
  add column if not exists "requester" text,
  add column if not exists "created_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- crew_members
create table if not exists public.crew_members (id text primary key);
alter table public.crew_members
  add column if not exists "site_id" text,
  add column if not exists "name" text,
  add column if not exists "role" text,
  add column if not exists "shift" text,
  add column if not exists "on_shift" boolean,
  add column if not exists "phone" text,
  add column if not exists "email" text,
  add column if not exists "contactable" boolean,
  add column if not exists "certifications" jsonb,
  add column if not exists "owns" jsonb,
  add column if not exists "synthetic" boolean,
  add column if not exists "generator" text,
  add column if not exists "updated_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- obligations
create table if not exists public.obligations (id text primary key);
alter table public.obligations
  add column if not exists "site_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "title" text,
  add column if not exists "rule_ref" text,
  add column if not exists "frequency" text,
  add column if not exists "last_done_at" timestamptz,
  add column if not exists "due_at" timestamptz,
  add column if not exists "status" text,
  add column if not exists "document_id" text,
  add column if not exists "owner_id" text,
  add column if not exists "blocked_by" text,
  add column if not exists "blocked_reason" text,
  add column if not exists "regulation_ids" jsonb,
  add column if not exists "note" text,
  add column if not exists "synthetic" boolean,
  add column if not exists "generator" text,
  add column if not exists "updated_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- issues
create table if not exists public.issues (id text primary key);
alter table public.issues
  add column if not exists "site_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "component_id" text,
  add column if not exists "kind" text,
  add column if not exists "severity" text,
  add column if not exists "status" text,
  add column if not exists "summary" text,
  add column if not exists "ref_id" text,
  add column if not exists "pin" jsonb,
  add column if not exists "at" timestamptz,
  add column if not exists "updated_at" timestamptz,
  add column if not exists "scenario_id" text,
  add column if not exists "run_id" text,
  add column if not exists "source" text,
  add column if not exists "owner_id" text,
  add column if not exists "assignee_id" text,
  add column if not exists "obligation_id" text,
  add column if not exists "document_id" text,
  add column if not exists "evidence_frame_ids" jsonb,
  add column if not exists "synthetic" boolean,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- conversations
create table if not exists public.conversations (id text primary key);
alter table public.conversations
  add column if not exists "kind" text,
  add column if not exists "topic" text,
  add column if not exists "convener" text,
  add column if not exists "participants" jsonb,
  add column if not exists "site_ids" jsonb,
  add column if not exists "transport" text,
  add column if not exists "provider_task_ids" jsonb,
  add column if not exists "a2a_task_ids" jsonb,
  add column if not exists "transcript" jsonb,
  add column if not exists "summary" jsonb,
  add column if not exists "summary_by" text,
  add column if not exists "started_at" timestamptz,
  add column if not exists "ended_at" timestamptz,
  add column if not exists "status" text,
  add column if not exists "issue_id" text,
  add column if not exists "issue_kind" text,
  add column if not exists "scenario_id" text,
  add column if not exists "run_id" text,
  add column if not exists "resolution" text,
  add column if not exists "contact" jsonb,
  add column if not exists "synthetic" boolean,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- viewer_commands
create table if not exists public.viewer_commands (id text primary key);
alter table public.viewer_commands
  add column if not exists "seq" bigint,
  add column if not exists "site_id" text,
  add column if not exists "action" text,
  add column if not exists "asset_tag" text,
  add column if not exists "issue_id" text,
  add column if not exists "pin" jsonb,
  add column if not exists "issued_by" text,
  add column if not exists "at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- memories
create table if not exists public.memories (id text primary key);
alter table public.memories
  add column if not exists "agent_id" text,
  add column if not exists "container" text,
  add column if not exists "kind" text,
  add column if not exists "content" text,
  add column if not exists "site_id" text,
  add column if not exists "refs" jsonb,
  add column if not exists "at" timestamptz,
  add column if not exists "synthetic" boolean,
  add column if not exists "provider_status" text,
  add column if not exists "provider_id" text,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- telemetry
create table if not exists public.telemetry (id text primary key);
alter table public.telemetry
  add column if not exists "at" timestamptz,
  add column if not exists "agent_id" text,
  add column if not exists "site_id" text,
  add column if not exists "kind" text,
  add column if not exists "tool" text,
  add column if not exists "tokens" integer,
  add column if not exists "ms" integer,
  add column if not exists "ok" boolean,
  add column if not exists "mission_id" text,
  add column if not exists "scenario_id" text,
  add column if not exists "run_id" text,
  add column if not exists "source" text,
  add column if not exists "synthetic" boolean,
  add column if not exists "detail" text,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- findings
create table if not exists public.findings (id text primary key);
alter table public.findings
  add column if not exists "site_id" text,
  add column if not exists "asset_tag" text,
  add column if not exists "component_id" text,
  add column if not exists "status" text,
  add column if not exists "score" numeric,
  add column if not exists "threshold" numeric,
  add column if not exists "model" text,
  add column if not exists "frames" jsonb,
  add column if not exists "explanation" jsonb,
  add column if not exists "issue_id" text,
  add column if not exists "source" text,
  add column if not exists "synthetic" boolean,
  add column if not exists "run_id" text,
  add column if not exists "ingested_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- notifications
create table if not exists public.notifications (id text primary key);
alter table public.notifications
  add column if not exists "site_id" text,
  add column if not exists "workflow_id" text,
  add column if not exists "issue_id" text,
  add column if not exists "sender" text,
  add column if not exists "to_kind" text,
  add column if not exists "to" text,
  add column if not exists "to_name" text,
  add column if not exists "channel" text,
  add column if not exists "text" text,
  add column if not exists "mode" text,
  add column if not exists "notice_id" text,
  add column if not exists "a2a_task_id" text,
  add column if not exists "transport" text,
  add column if not exists "synthetic" boolean,
  add column if not exists "at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- maintenance_windows
create table if not exists public.maintenance_windows (id text primary key);
alter table public.maintenance_windows
  add column if not exists "site_ids" jsonb,
  add column if not exists "date" date,
  add column if not exists "scope" text,
  add column if not exists "examiner" text,
  add column if not exists "status" text,
  add column if not exists "conversation_id" text,
  add column if not exists "approval_conversation_id" text,
  add column if not exists "asset_tags" jsonb,
  add column if not exists "obligation_id" text,
  add column if not exists "proposed_by" text,
  add column if not exists "approved_by" text,
  add column if not exists "scenario_id" text,
  add column if not exists "synthetic" boolean,
  add column if not exists "created_at" timestamptz,
  add column if not exists "updated_at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- eye_frames
create table if not exists public.eye_frames (id text primary key);
alter table public.eye_frames
  add column if not exists "seq" bigint,
  add column if not exists "site_id" text,
  add column if not exists "command_id" text,
  add column if not exists "action" text,
  add column if not exists "params" jsonb,
  add column if not exists "actor" text,
  add column if not exists "camera" jsonb,
  add column if not exists "visible_pins" jsonb,
  add column if not exists "index" integer,
  add column if not exists "renderer_id" text,
  add column if not exists "size" integer,
  add column if not exists "sha256" text,
  add column if not exists "url" text,
  add column if not exists "at" timestamptz,
  add column if not exists written_by text,
  add column if not exists mirrored_at timestamptz;

-- Attestation ledger columns (see 0004_ledger.sql): the exact canonical JSON the backend signed, and the hash chain.
alter table public.attestations
  add column if not exists signed_payload text,
  add column if not exists chain_seq bigint,
  add column if not exists prev_hash text,
  add column if not exists row_hash text;

-- Converge a 0001 database: drop its CHECK constraints and NOT NULLs (the mirror may omit any column but id).
do $$
declare
  r record;
begin
  for r in
    select c.conrelid::regclass as tbl, c.conname
    from pg_constraint c
    where c.contype = 'c'
      and c.conrelid::regclass::text in ('public.facts', 'public.attestations', 'public.work_items', 'public.dispatches',
                                         'public.changes', 'public.subscriptions')
  loop
    execute format('alter table %s drop constraint if exists %I', r.tbl, r.conname);
  end loop;
  for r in
    select a.attrelid::regclass as tbl, a.attname
    from pg_attribute a
    join pg_class t on t.oid = a.attrelid
    join pg_namespace n on n.oid = t.relnamespace
    where n.nspname = 'public' and a.attnum > 0 and not a.attisdropped and a.attnotnull and a.attname <> 'id'
      and t.relname in ('facts', 'attestations', 'work_items', 'dispatches', 'changes', 'subscriptions', 'crew_members',
                        'obligations', 'issues', 'conversations', 'viewer_commands', 'memories', 'telemetry', 'findings',
                        'notifications', 'maintenance_windows', 'eye_frames')
  loop
    execute format('alter table %s alter column %I drop not null', r.tbl, r.attname);
  end loop;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- Agents: one row per agent, one Supabase Auth user per row (auth_user_id is filled by backend/scripts/supabase_agents.py)
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.agents (
  id            text primary key,
  level         integer not null,
  site_id       text,
  role          text not null,
  display_name  text not null,
  auth_user_id  uuid unique
);
alter table public.agents drop constraint if exists agents_role_check;
alter table public.agents add constraint agents_role_check
  check (role in ('operator', 'director', 'manager', 'engineer', 'compliance', 'technician'));

insert into public.agents (id, level, site_id, role, display_name) values
  ('operator',           1, null,            'operator',   'Owner''s agent'),
  ('director',           2, null,            'director',   'Operations Director'),
  ('myer-manager',       3, 'myer-plant',    'manager',    'Plant Manager · Myer'),
  ('myer-engineer',      4, 'myer-plant',    'engineer',   'Site Engineer · Myer'),
  ('myer-compliance',    4, 'myer-plant',    'compliance', 'Compliance Officer · Myer'),
  ('myer-technician',    5, 'myer-plant',    'technician', 'Field Technician · Myer'),
  ('bristol-manager',    3, 'bristol-pumps', 'manager',    'Plant Manager · Bristol'),
  ('bristol-engineer',   4, 'bristol-pumps', 'engineer',   'Site Engineer · Bristol'),
  ('bristol-compliance', 4, 'bristol-pumps', 'compliance', 'Compliance Officer · Bristol'),
  ('bristol-technician', 5, 'bristol-pumps', 'technician', 'Field Technician · Bristol'),
  ('tomioka-manager',    3, 'tomioka-mill',  'manager',    'Site Manager · Tomioka'),
  ('tomioka-engineer',   4, 'tomioka-mill',  'engineer',   'Conservation Engineer · Tomioka'),
  ('tomioka-compliance', 4, 'tomioka-mill',  'compliance', 'Compliance Officer · Tomioka'),
  ('tomioka-technician', 5, 'tomioka-mill',  'technician', 'Field Technician · Tomioka')
on conflict (id) do update
  set level = excluded.level, site_id = excluded.site_id, role = excluded.role, display_name = excluded.display_name;

-- ---------------------------------------------------------------------------------------------------------------
-- Indexes: (property_id, version) and the lookup keys
-- ---------------------------------------------------------------------------------------------------------------
create index if not exists facts_property_version_idx        on public.facts (property_id, version);
create index if not exists facts_property_tag_attr_idx       on public.facts (property_id, asset_tag, attribute);
create index if not exists facts_attestation_idx             on public.facts (attestation_id);
create index if not exists attestations_property_tag_attr_idx on public.attestations (property_id, asset_tag, attribute);
create index if not exists attestations_property_signed_idx  on public.attestations (property_id, signed_at desc);
create unique index if not exists attestations_chain_seq_idx on public.attestations (chain_seq);
create index if not exists work_items_property_state_idx     on public.work_items (property_id, state);
create index if not exists work_items_property_tag_attr_idx  on public.work_items (property_id, asset_tag, attribute);
create index if not exists work_items_reference_idx          on public.work_items (reference);
create index if not exists dispatches_work_item_idx          on public.dispatches (work_item_id);
create index if not exists dispatches_property_sent_idx      on public.dispatches (property_id, sent_at desc);
create unique index if not exists changes_property_version_idx on public.changes (property_id, version);
create index if not exists changes_property_at_idx           on public.changes (property_id, at desc);
create index if not exists subscriptions_property_idx        on public.subscriptions (property_id);
create index if not exists crew_members_site_idx             on public.crew_members (site_id);
create index if not exists obligations_site_status_idx       on public.obligations (site_id, status);
create index if not exists obligations_site_due_idx          on public.obligations (site_id, due_at);
create index if not exists issues_site_status_idx            on public.issues (site_id, status);
create index if not exists issues_site_asset_idx             on public.issues (site_id, asset_tag);
create index if not exists conversations_started_idx         on public.conversations (started_at desc);
create index if not exists conversations_site_ids_idx        on public.conversations using gin (site_ids jsonb_path_ops);
create index if not exists viewer_commands_site_seq_idx      on public.viewer_commands (site_id, seq);
create index if not exists memories_agent_at_idx             on public.memories (agent_id, at desc);
create index if not exists telemetry_agent_at_idx            on public.telemetry (agent_id, at desc);
create index if not exists telemetry_site_at_idx             on public.telemetry (site_id, at desc);
create index if not exists findings_site_asset_idx           on public.findings (site_id, asset_tag);
create index if not exists findings_run_idx                  on public.findings (run_id);
create index if not exists notifications_site_at_idx         on public.notifications (site_id, at desc);
create index if not exists maintenance_windows_date_idx      on public.maintenance_windows (date);
create index if not exists maintenance_windows_site_ids_idx  on public.maintenance_windows using gin (site_ids jsonb_path_ops);
create index if not exists eye_frames_site_seq_idx           on public.eye_frames (site_id, seq);
create index if not exists agents_site_idx                   on public.agents (site_id);

-- ---------------------------------------------------------------------------------------------------------------
-- Secure baseline: RLS on everywhere; anon and authenticated hold nothing until 0003 grants it.
-- Supabase's default privileges grant ALL on new public tables to anon and authenticated, so revoke explicitly.
-- ---------------------------------------------------------------------------------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array['facts', 'attestations', 'work_items', 'dispatches', 'changes', 'subscriptions', 'crew_members',
                           'obligations', 'issues', 'conversations', 'viewer_commands', 'memories', 'telemetry', 'findings',
                           'notifications', 'maintenance_windows', 'eye_frames', 'agents']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    if t = 'attestations' then
      -- append-only ledger (0004): the service role may read and append, never change or remove
      execute format('revoke update, delete, truncate on public.%I from service_role', t);
      execute format('grant select, insert on public.%I to service_role', t);
    else
      execute format('grant select, insert, update, delete on public.%I to service_role', t);
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- Writer stamp: who wrote the row comes from the caller's JWT, never from the payload.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function steward.stamp_row() returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_claims jsonb := coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb;
begin
  new.written_by := coalesce(nullif(v_claims ->> 'agent_id', ''), nullif(v_claims ->> 'role', ''), current_user::text);
  new.mirrored_at := now();
  return new;
end
$$;

do $$
declare
  t text;
begin
  foreach t in array array['facts', 'attestations', 'work_items', 'dispatches', 'changes', 'subscriptions', 'crew_members',
                           'obligations', 'issues', 'conversations', 'viewer_commands', 'memories', 'telemetry', 'findings',
                           'notifications', 'maintenance_windows', 'eye_frames']
  loop
    execute format('drop trigger if exists steward_10_stamp on public.%I', t);
    execute format('create trigger steward_10_stamp before insert or update on public.%I for each row execute function steward.stamp_row()', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- Realtime: only the small tables the dashboard needs (changes, issues, notifications); never the large ones.
-- Postgres Changes apply RLS per subscriber; 0003 gives anon no SELECT on these, so anon receives none of them.
-- ---------------------------------------------------------------------------------------------------------------
do $$
declare
  t text;
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
  foreach t in array array['changes', 'issues', 'notifications'] loop
    if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
  -- 0001 published facts and work_items; they are large, so take them out.
  foreach t in array array['facts', 'work_items', 'attestations', 'telemetry', 'memories', 'eye_frames', 'conversations'] loop
    if exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime drop table public.%I', t);
    end if;
  end loop;
end $$;
