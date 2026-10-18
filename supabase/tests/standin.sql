-- A local stand-in for the parts of a Supabase database the Steward migrations touch, so the migrations, RLS policies,
-- the ledger triggers and the queue wrappers can be tested on a throwaway local Postgres (backend/tests/test_supabase_sql.py).
-- It mirrors what was read from the hosted project: the roles (service_role has BYPASSRLS), auth.uid()/auth.jwt()/
-- realtime.topic() definitions, realtime.messages, storage.buckets/objects, and Supabase's default privileges that grant
-- anon and authenticated ALL on new public tables and EXECUTE on new public functions. pgmq is a minimal SQL stub with the
-- 1.5.1 signatures the migrations call; pg_cron and pgsodium are absent, so their guarded blocks are skipped.

create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;
create role supabase_auth_admin nologin noinherit;
create role authenticator login noinherit;
grant anon, authenticated, service_role to authenticator;

create schema extensions;
create extension pgcrypto with schema extensions;
create schema auth;
create schema realtime;
create schema storage;
grant usage on schema public, auth, realtime, storage, extensions to anon, authenticated, service_role;

alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;

create table auth.users (id uuid primary key default gen_random_uuid(), email text unique);

create function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid
$$;
create function auth.role() returns text language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'))::text
$$;
create function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''), nullif(current_setting('request.jwt.claims', true), ''))::jsonb
$$;
grant execute on all functions in schema auth to anon, authenticated, service_role;

create table realtime.messages (
  topic text not null, extension text not null, payload jsonb, event text, private boolean default false,
  updated_at timestamp not null default now(), inserted_at timestamp not null default now(), id uuid not null default gen_random_uuid());
alter table realtime.messages enable row level security;
grant select, insert, update on realtime.messages to anon, authenticated, service_role;
create function realtime.topic() returns text language sql stable as $$ select nullif(current_setting('realtime.topic', true), '')::text $$;
grant execute on function realtime.topic() to anon, authenticated, service_role;

create table storage.buckets (
  id text primary key, name text not null, owner uuid, created_at timestamptz default now(), updated_at timestamptz default now(),
  public boolean default false, avif_autodetection boolean default false, file_size_limit bigint, allowed_mime_types text[], owner_id text);
create table storage.objects (
  id uuid primary key default gen_random_uuid(), bucket_id text references storage.buckets (id), name text, owner uuid,
  created_at timestamptz default now(), updated_at timestamptz default now(), last_accessed_at timestamptz default now(), metadata jsonb);
alter table storage.buckets enable row level security;
alter table storage.objects enable row level security;
grant all on storage.buckets, storage.objects to anon, authenticated, service_role;

create publication supabase_realtime;

-- pgmq 1.5.1 stub: create / send / read / archive with the hosted signatures.
create schema pgmq;
create type pgmq.message_record as (msg_id bigint, read_ct integer, enqueued_at timestamptz, vt timestamptz, message jsonb, headers jsonb);
create function pgmq.create(queue_name text) returns void language plpgsql as $$
begin
  execute format('create table if not exists pgmq.%I (msg_id bigserial primary key, read_ct integer not null default 0,
                  enqueued_at timestamptz not null default now(), vt timestamptz not null default now(), message jsonb, headers jsonb)', 'q_' || queue_name);
  execute format('create table if not exists pgmq.%I (msg_id bigint primary key, read_ct integer, enqueued_at timestamptz,
                  archived_at timestamptz not null default now(), vt timestamptz, message jsonb, headers jsonb)', 'a_' || queue_name);
end $$;
create function pgmq.send(queue_name text, msg jsonb) returns setof bigint language plpgsql as $$
begin
  return query execute format('insert into pgmq.%I (message) values ($1) returning msg_id', 'q_' || queue_name) using msg;
end $$;
create function pgmq.read(queue_name text, vt integer, qty integer, conditional jsonb default '{}') returns setof pgmq.message_record
language plpgsql as $$
begin
  return query execute format(
    'with picked as (select msg_id from pgmq.%1$I where vt <= now() order by msg_id limit $1 for update skip locked)
     update pgmq.%1$I q set vt = now() + make_interval(secs => $2), read_ct = q.read_ct + 1 from picked where q.msg_id = picked.msg_id
     returning q.msg_id, q.read_ct, q.enqueued_at, q.vt, q.message, q.headers', 'q_' || queue_name) using qty, vt;
end $$;
create function pgmq.archive(queue_name text, msg_id bigint) returns boolean language plpgsql as $$
declare
  n integer;
begin
  execute format('with moved as (delete from pgmq.%I where msg_id = $1 returning *)
                  insert into pgmq.%I (msg_id, read_ct, enqueued_at, vt, message, headers)
                  select msg_id, read_ct, enqueued_at, vt, message, headers from moved', 'q_' || queue_name, 'a_' || queue_name) using msg_id;
  get diagnostics n = row_count;
  return n > 0;
end $$;
