-- SUPERSEDED by 0002_steward.sql .. 0007_storage.sql (see supabase/README.md). Do not apply this file: its NOT NULLs, CHECKs
-- and anon reads no longer match the mirror. 0002 converges a database that already ran it.
-- Steward reality layer: Supabase mirror of the backend's SQLite source of truth.
-- Written against REALITY-CONTRACT.md (domain types) on 2026-10-17.
-- Column names are snake_case versions of the contract's camelCase JSON fields.
-- Nested objects/arrays are jsonb. IDs are text primary keys. Timestamps are timestamptz.
-- The backend upserts rows through PostgREST on `id` (see backend/README.md); the frontend
-- reads facts/attestations/changes with the anon (publishable) key and subscribes to Realtime.
-- Safe to re-run: every statement is idempotent.

-- --------------------------------------------------------------------------
-- Enumerations as CHECK constraints (kept in sync with shared/types.ts)
-- --------------------------------------------------------------------------
-- AttributeClass: reading | condition | document | identity
-- SourceKind:     scan | camera | sensor | patrol | human | agent | owner (inside the `source` jsonb)
-- Verdict:        accepted | rejected | needs_clarification
-- WorkState:      open | dispatched | waiting | needs_clarification | escalated | resolved | rejected | expired
-- Channel:        local | email | sms | imessage | call
-- Change.type:    fact | work_item | attestation | dispatch | escalation | owner_decision

-- --------------------------------------------------------------------------
-- properties: the three sites (seeded by supabase/seed.sql). Not in the contract
-- type list but needed so every mirrored row can reference a site.
-- --------------------------------------------------------------------------
create table if not exists public.properties (
  id          text primary key,              -- cedar | harbor | juniper
  name        text not null,
  address     text,
  phase       text,
  created_at  timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- facts (contract: Fact)
-- --------------------------------------------------------------------------
create table if not exists public.facts (
  id               text primary key,
  property_id      text not null,
  asset_tag        text not null,
  component_id     text not null,
  attribute        text not null,
  attribute_class  text not null check (attribute_class in ('reading','condition','document','identity')),
  value            jsonb not null,            -- string | number | boolean
  unit             text,
  observed_at      timestamptz not null,
  ttl_seconds      bigint,                    -- null = never expires (identity)
  expires_at       timestamptz,
  source           jsonb not null,            -- {kind, ref}
  attestation_id   text not null,
  version          bigint not null,
  created_at       timestamptz not null default now()
);
create index if not exists facts_property_tag_attr_idx on public.facts (property_id, asset_tag, attribute);
create index if not exists facts_property_version_idx  on public.facts (property_id, version);
create index if not exists facts_attestation_idx       on public.facts (attestation_id);

-- --------------------------------------------------------------------------
-- attestations (contract: Attestation). Signed Ed25519 record; payload =
-- canonical JSON of every field except `signature`.
-- --------------------------------------------------------------------------
create table if not exists public.attestations (
  id                text primary key,
  property_id       text not null,
  asset_tag         text not null,
  component_id      text not null,
  attribute         text not null,
  value             jsonb not null,
  unit              text,
  observed_at       timestamptz not null,
  evidence_hashes   jsonb not null default '[]'::jsonb,   -- string[] of SHA-256 hex
  checks            jsonb not null default '[]'::jsonb,   -- Check[] {name, passed, reason}
  verdict           text not null check (verdict in ('accepted','rejected','needs_clarification')),
  source            jsonb not null,                       -- {kind, ref}
  verifier_version  text not null,                        -- "steward-verify/1"
  signed_at         timestamptz not null,
  public_key        text not null,                        -- base64 Ed25519 public key
  signature         text not null,                        -- base64 Ed25519 signature
  created_at        timestamptz not null default now()
);
create index if not exists attestations_property_tag_attr_idx on public.attestations (property_id, asset_tag, attribute);
create index if not exists attestations_property_signed_idx   on public.attestations (property_id, signed_at desc);

-- --------------------------------------------------------------------------
-- work_items (contract: WorkItem). dispatches[] and verdicts[] are embedded
-- jsonb exactly as the API returns them; receipt is jsonb or null.
-- --------------------------------------------------------------------------
create table if not exists public.work_items (
  id               text primary key,
  property_id      text not null,
  asset_tag        text not null,
  component_id     text not null,
  attribute        text not null,
  attribute_class  text not null check (attribute_class in ('reading','condition','document','identity')),
  reference        text not null,             -- e.g. HW-P101-PRESSURE_BAR-0042
  state            text not null check (state in ('open','dispatched','waiting','needs_clarification','escalated','resolved','rejected','expired')),
  requester        text not null,
  budget           numeric(12,2) not null default 0,
  deadline_at      timestamptz,
  dispatches       jsonb not null default '[]'::jsonb,   -- Dispatch[]
  verdicts         jsonb not null default '[]'::jsonb,   -- {attestationId, verdict, reasons[], at}[]
  fact_id          text,
  attestation_id   text,
  receipt          jsonb,                                -- Receipt | null
  created_at       timestamptz not null,
  updated_at       timestamptz not null
);
create index if not exists work_items_property_tag_attr_idx on public.work_items (property_id, asset_tag, attribute);
create index if not exists work_items_property_state_idx    on public.work_items (property_id, state);
create unique index if not exists work_items_reference_idx   on public.work_items (reference);

-- --------------------------------------------------------------------------
-- dispatches (contract: Dispatch) flattened out of work_items so the timeline
-- can be queried per channel. `to` is a reserved word in SQL and is quoted;
-- PostgREST accepts it as a plain JSON key ("to").
-- --------------------------------------------------------------------------
create table if not exists public.dispatches (
  id             text primary key,
  work_item_id   text,
  property_id    text,
  channel        text not null check (channel in ('local','email','sms','imessage','call')),
  "to"           text not null,
  reference      text not null,
  sent_at        timestamptz not null,
  provider_ref   text,                        -- Inkbox message/call id, null for local or unplaced calls
  body           text not null,
  created_at     timestamptz not null default now()
);
create index if not exists dispatches_work_item_idx on public.dispatches (work_item_id);
create index if not exists dispatches_property_sent_idx on public.dispatches (property_id, sent_at desc);

-- --------------------------------------------------------------------------
-- changes (contract: Change). The contract type has no id; the mirror needs one
-- for upsert-on-id. Convention: id = property_id || ':' || version.
-- --------------------------------------------------------------------------
create table if not exists public.changes (
  id           text primary key,
  version      bigint not null,
  type         text not null check (type in ('fact','work_item','attestation','dispatch','escalation','owner_decision')),
  property_id  text not null,
  asset_tag    text,
  ref_id       text not null,
  summary      text not null,
  at           timestamptz not null,
  created_at   timestamptz not null default now()
);
create unique index if not exists changes_property_version_idx on public.changes (property_id, version);
create index if not exists changes_property_at_idx on public.changes (property_id, at desc);

-- --------------------------------------------------------------------------
-- subscriptions (contract: Subscription): A2A callback registrations.
-- --------------------------------------------------------------------------
create table if not exists public.subscriptions (
  id            text primary key,
  property_id   text not null,
  callback_url  text not null,
  requester     text not null,
  created_at    timestamptz not null default now()
);
create index if not exists subscriptions_property_idx on public.subscriptions (property_id);

-- --------------------------------------------------------------------------
-- Row level security.
-- service_role (the backend's SUPABASE_SERVICE_KEY / sb_secret_ key) has the
-- BYPASSRLS attribute, so the explicit "service role everything" policies below
-- are documentation of intent and a safety net if that attribute ever changes.
-- anon (the frontend's publishable / legacy anon key) can only SELECT from
-- facts, attestations and changes. No anon access to work_items, dispatches,
-- subscriptions or properties beyond read of properties.
-- --------------------------------------------------------------------------
alter table public.properties    enable row level security;
alter table public.facts         enable row level security;
alter table public.attestations  enable row level security;
alter table public.work_items    enable row level security;
alter table public.dispatches    enable row level security;
alter table public.changes       enable row level security;
alter table public.subscriptions enable row level security;

do $$
declare t text;
begin
  foreach t in array array['properties','facts','attestations','work_items','dispatches','changes','subscriptions'] loop
    execute format('drop policy if exists "service role everything" on public.%I', t);
    execute format('create policy "service role everything" on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  foreach t in array array['properties','facts','attestations','changes'] loop
    execute format('drop policy if exists "anon read only" on public.%I', t);
    execute format('create policy "anon read only" on public.%I for select to anon using (true)', t);
  end loop;
end $$;

grant usage on schema public to anon, service_role;
grant select on public.properties, public.facts, public.attestations, public.changes to anon;
revoke all on public.work_items, public.dispatches, public.subscriptions from anon;
grant all on public.properties, public.facts, public.attestations, public.work_items, public.dispatches, public.changes, public.subscriptions to service_role;

-- --------------------------------------------------------------------------
-- Realtime. The dashboard subscribes to postgres_changes on `changes`
-- (and may also watch facts / work_items). Realtime applies RLS to
-- postgres_changes, so an anon subscriber receives facts and changes events
-- but NOT work_items events (no anon policy there by design; the dashboard
-- reads work items through the backend API). Guarded so re-running the
-- migration does not fail with "already member of publication".
-- --------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['changes','work_items','facts'] loop
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t
    ) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;

-- Old row values on UPDATE/DELETE events (optional; inserts do not need it).
alter table public.changes replica identity full;
