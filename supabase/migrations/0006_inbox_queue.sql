-- 0006_inbox_queue.sql: the inbox that never sleeps. Idempotent.
--
-- The Edge Function supabase/functions/inkbox-inbox verifies the Inkbox webhook signature and calls
-- public.inkbox_enqueue(), which counts the call against the daily cap, deduplicates on the envelope id and sends the
-- exact request (raw body bytes and signature headers) to the pgmq queue `inkbox_inbound`. The backend drains it
-- every 5 s with public.inkbox_inbox_read / public.inkbox_inbox_archive (secret key only) and replays each message
-- through POST /api/inbound/inkbox, which verifies the signature again. Archived messages are deleted after 3 days.

do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pgmq') then
    create extension if not exists pgmq;
  end if;
end $$;

do $$
begin
  if to_regnamespace('pgmq') is not null and to_regclass('pgmq.q_inkbox_inbound') is null then
    perform pgmq.create('inkbox_inbound');
  end if;
end $$;

-- Queue tables hold message bodies: nobody but the owner and the SECURITY DEFINER wrappers below may touch them.
do $$
begin
  if to_regnamespace('pgmq') is not null then
    execute 'revoke all on schema pgmq from public, anon, authenticated';
    execute 'revoke all on all tables in schema pgmq from public, anon, authenticated';
    execute 'revoke all on all sequences in schema pgmq from public, anon, authenticated';
    execute 'revoke execute on all functions in schema pgmq from public, anon, authenticated';
  end if;
end $$;

create table if not exists steward.inbox_seen (
  envelope_id text primary key,
  request_id  text,
  event_type  text,
  msg_id      bigint,
  received_at timestamptz not null default now()
);
create index if not exists inbox_seen_received_idx on steward.inbox_seen (received_at);

create table if not exists steward.edge_calls (
  day      date primary key,
  calls    integer not null default 0,
  refused  integer not null default 0
);

create table if not exists steward.settings (
  key        text primary key,
  value      text not null,
  updated_at timestamptz not null default now()
);
insert into steward.settings (key, value) values ('edge_calls_day_cap', '5000') on conflict (key) do nothing;

revoke all on steward.inbox_seen, steward.edge_calls, steward.settings from public, anon, authenticated;
grant select on steward.inbox_seen, steward.edge_calls, steward.settings to service_role;

-- Called by the Edge Function (secret key) once per signed request.
create or replace function public.inkbox_enqueue(p_envelope_id text, p_request_id text, p_event_type text, p_message jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_cap   integer;
  v_calls integer;
  v_msg   bigint;
  v_day   date := (now() at time zone 'utc')::date;
begin
  v_cap := coalesce((select s.value::integer from steward.settings s where s.key = 'edge_calls_day_cap'), 5000);
  insert into steward.edge_calls as e (day, calls) values (v_day, 1)
  on conflict (day) do update set calls = e.calls + 1
  returning e.calls into v_calls;
  if v_calls > v_cap then
    update steward.edge_calls set refused = refused + 1 where day = v_day;
    return jsonb_build_object('accepted', false, 'reason', 'daily Edge Function cap reached', 'calls', v_calls, 'cap', v_cap);
  end if;
  if p_envelope_id is null or length(p_envelope_id) = 0 or length(p_envelope_id) > 200 then
    return jsonb_build_object('accepted', false, 'reason', 'missing envelope id');
  end if;
  insert into steward.inbox_seen (envelope_id, request_id, event_type) values (p_envelope_id, left(p_request_id, 200), left(p_event_type, 60))
  on conflict (envelope_id) do nothing;
  if not found then
    return jsonb_build_object('accepted', true, 'duplicate', true, 'calls', v_calls, 'cap', v_cap);
  end if;
  select pgmq.send('inkbox_inbound', p_message) into v_msg;
  update steward.inbox_seen set msg_id = v_msg where envelope_id = p_envelope_id;
  return jsonb_build_object('accepted', true, 'duplicate', false, 'msgId', v_msg, 'calls', v_calls, 'cap', v_cap);
end
$$;

-- Backend drain wrappers (secret key only).
create or replace function public.inkbox_inbox_read(p_qty integer default 10, p_vt integer default 60)
returns table (msg_id bigint, read_ct integer, enqueued_at timestamptz, message jsonb)
language sql
security definer
set search_path = ''
as $$
  select r.msg_id, r.read_ct, r.enqueued_at, r.message
  from pgmq.read('inkbox_inbound', greatest(least(p_vt, 600), 5), greatest(least(p_qty, 50), 1)) as r
$$;

create or replace function public.inkbox_inbox_archive(p_msg_id bigint) returns boolean
language sql
security definer
set search_path = ''
as $$ select pgmq.archive('inkbox_inbound', p_msg_id) $$;

create or replace function public.inkbox_inbox_stats() returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'queued', (select count(*) from pgmq.q_inkbox_inbound),
    'archived', (select count(*) from pgmq.a_inkbox_inbound),
    'callsToday', coalesce((select e.calls from steward.edge_calls e where e.day = (now() at time zone 'utc')::date), 0),
    'refusedToday', coalesce((select e.refused from steward.edge_calls e where e.day = (now() at time zone 'utc')::date), 0),
    'cap', (select s.value::integer from steward.settings s where s.key = 'edge_calls_day_cap'),
    'day', (now() at time zone 'utc')::date)
$$;

create or replace function public.steward_put_setting(p_key text, p_value text) returns boolean
language sql
security definer
set search_path = ''
as $$
  insert into steward.settings (key, value, updated_at) values (p_key, p_value, now())
  on conflict (key) do update set value = excluded.value, updated_at = now()
  returning true
$$;

revoke all on function public.inkbox_enqueue(text, text, text, jsonb) from public, anon, authenticated;
revoke all on function public.inkbox_inbox_read(integer, integer) from public, anon, authenticated;
revoke all on function public.inkbox_inbox_archive(bigint) from public, anon, authenticated;
revoke all on function public.inkbox_inbox_stats() from public, anon, authenticated;
revoke all on function public.steward_put_setting(text, text) from public, anon, authenticated;
grant execute on function public.inkbox_enqueue(text, text, text, jsonb) to service_role;
grant execute on function public.inkbox_inbox_read(integer, integer) to service_role;
grant execute on function public.inkbox_inbox_archive(bigint) to service_role;
grant execute on function public.inkbox_inbox_stats() to service_role;
grant execute on function public.steward_put_setting(text, text) to service_role;

-- Retention (pg_cron, once a day): archived bodies after 3 days, dedupe ids after 30 days, counters after 60 days.
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    perform cron.schedule('steward-inbox-retention', '17 3 * * *', $job$
      delete from pgmq.a_inkbox_inbound where archived_at < now() - interval '3 days';
      delete from steward.inbox_seen where received_at < now() - interval '30 days';
      delete from steward.edge_calls where day < (now() at time zone 'utc')::date - 60;
    $job$);
  end if;
end $$;
