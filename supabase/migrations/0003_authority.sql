-- 0003_authority.sql: authority in Postgres. Idempotent.
--
-- One Supabase Auth user per agent (backend/scripts/supabase_agents.py creates them with the service key and links
-- public.agents.auth_user_id). A custom access token hook adds the claims agent_id, agent_level, site_id (and
-- agent_role) from public.agents. RLS mirrors the authority table in REALITY-CONTRACT-4.md section 1:
--   * reads are scoped by site (operator and director read both sites);
--   * writes only by the roles allowed, only for the agent's own site (shared rows: a participating site);
--   * technicians can never insert attestations or facts; compliance writes obligations and notices;
--   * rows that name their author (telemetry, memories, eye frames, viewer commands, notifications, conversations) can
--     only be written by that author;
--   * anon reads only four non-sensitive tables (facts, eye_frames, findings, maintenance_windows) and nothing that
--     could hold contact details or document text.
-- The service role (secret key) bypasses RLS and is used only for setup, migrations and system rows.

-- ---------------------------------------------------------------------------------------------------------------
-- Custom access token hook (enabled with supabase/config.toml [auth.hook.custom_access_token] + `supabase config push`)
-- ---------------------------------------------------------------------------------------------------------------
create or replace function steward.custom_access_token_hook(event jsonb) returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
  v_agent  public.agents;
begin
  select a.* into v_agent from public.agents a where a.auth_user_id = (event ->> 'user_id')::uuid;
  if v_agent.id is null then
    v_claims := v_claims - 'agent_id' - 'agent_level' - 'site_id' - 'agent_role';
  else
    v_claims := v_claims || jsonb_build_object('agent_id', v_agent.id, 'agent_level', v_agent.level,
                                               'site_id', v_agent.site_id, 'agent_role', v_agent.role);
  end if;
  return jsonb_build_object('claims', v_claims);
end
$$;

grant usage on schema steward to supabase_auth_admin;
revoke execute on function steward.custom_access_token_hook(jsonb) from public, anon, authenticated;
grant execute on function steward.custom_access_token_hook(jsonb) to supabase_auth_admin;

-- ---------------------------------------------------------------------------------------------------------------
-- Who is calling: the agent row for auth.uid(), cross-checked against the agent_id claim when the hook set one.
-- SECURITY DEFINER so RLS on public.agents never recurses; wrapped as (select ...) in policies, evaluated once per query.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function steward.agent_id() returns text
language sql stable security definer set search_path = ''
as $$
  select a.id from public.agents a
  where a.auth_user_id = (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid
    and a.id = coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'agent_id', a.id)
$$;

create or replace function steward.agent_role() returns text
language sql stable security definer set search_path = ''
as $$
  select a.role from public.agents a where a.id = steward.agent_id()
$$;

create or replace function steward.agent_site() returns text
language sql stable security definer set search_path = ''
as $$
  select a.site_id from public.agents a where a.id = steward.agent_id()
$$;

create or replace function steward.agent_is_global() returns boolean
language sql stable security definer set search_path = ''
as $$
  select coalesce((select a.role in ('operator', 'director') from public.agents a where a.id = steward.agent_id()), false)
$$;

revoke all on function steward.agent_id(), steward.agent_role(), steward.agent_site(), steward.agent_is_global() from public, anon;
grant usage on schema steward to authenticated;
grant execute on function steward.agent_id(), steward.agent_role(), steward.agent_site(), steward.agent_is_global() to authenticated, service_role;

-- ---------------------------------------------------------------------------------------------------------------
-- The authority matrix. backend/src/supa_authority.py WRITE_ROLES mirrors this list (a test keeps them identical).
--   site_kind: one  = a single site column; many = a jsonb array of site ids; none = no site (the roster)
--   bind_col:  the column that must equal the writing agent's id
--   extra_check: an integrity rule every agent write must also pass (attestations need the signed payload, which
--     0004's trigger verifies with Ed25519; a fact must cite an attestation already in the ledger)
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists steward.authority (
  tbl         text primary key,
  site_col    text,
  site_kind   text not null check (site_kind in ('one', 'many', 'none')),
  writers     text[] not null,
  bind_col    text,
  append_only boolean not null default false,
  extra_check text
);
alter table steward.authority add column if not exists extra_check text;
revoke all on steward.authority from public, anon, authenticated;
grant select on steward.authority to service_role;

insert into steward.authority (tbl, site_col, site_kind, writers, bind_col, append_only) values
  ('facts',               'property_id', 'one',  array['operator', 'engineer'], null, false),
  ('attestations',        'property_id', 'one',  array['operator', 'engineer'], null, true),
  ('work_items',          'property_id', 'one',  array['operator', 'director', 'manager', 'engineer', 'technician'], null, false),
  ('dispatches',          'property_id', 'one',  array['operator', 'engineer', 'technician'], null, false),
  ('changes',             'property_id', 'one',  array[]::text[], null, false),
  ('subscriptions',       'property_id', 'one',  array['operator', 'engineer'], null, false),
  ('crew_members',        'site_id',     'one',  array['operator', 'manager'], null, false),
  ('obligations',         'site_id',     'one',  array['compliance'], null, false),
  ('issues',              'site_id',     'one',  array['operator', 'director', 'manager', 'engineer', 'compliance'], null, false),
  ('conversations',       'site_ids',    'many', array['operator', 'director', 'manager', 'engineer', 'compliance', 'technician'], 'convener', false),
  ('viewer_commands',     'site_id',     'one',  array['operator', 'director', 'manager', 'engineer', 'compliance'], 'issued_by', false),
  ('memories',            'site_id',     'one',  array['operator', 'director', 'manager', 'engineer', 'compliance', 'technician'], 'agent_id', false),
  ('telemetry',           'site_id',     'one',  array['operator', 'director', 'manager', 'engineer', 'compliance', 'technician'], 'agent_id', false),
  ('findings',            'site_id',     'one',  array['operator', 'director', 'manager', 'engineer'], null, false),
  ('notifications',       'site_id',     'one',  array['operator', 'director', 'manager', 'engineer', 'compliance', 'technician'], 'sender', false),
  ('maintenance_windows', 'site_ids',    'many', array['operator', 'director', 'manager'], null, false),
  ('eye_frames',          'site_id',     'one',  array['operator', 'director', 'manager', 'engineer'], 'actor', false),
  ('agents',              null,          'none', array[]::text[], null, false)
on conflict (tbl) do update
  set site_col = excluded.site_col, site_kind = excluded.site_kind, writers = excluded.writers,
      bind_col = excluded.bind_col, append_only = excluded.append_only;

update steward.authority set extra_check = 'signed_payload is not null' where tbl = 'attestations';
update steward.authority set extra_check = 'attestation_id is not null and exists (select 1 from public.attestations a where a.id = facts.attestation_id)'
  where tbl = 'facts';
update steward.authority set extra_check = null where tbl not in ('attestations', 'facts');

-- Policies are generated from the matrix so SQL and the backend can never drift apart silently.
do $$
declare
  r          record;
  p          record;
  v_site     text;
  v_read     text;
  v_write    text;
  v_nullable boolean;
begin
  for r in select * from steward.authority order by tbl loop
    for p in select policyname from pg_policies where schemaname = 'public' and tablename = r.tbl and policyname like 'steward %' loop
      execute format('drop policy %I on public.%I', p.policyname, r.tbl);
    end loop;
    execute format('revoke all on public.%I from public, anon, authenticated', r.tbl);

    -- telemetry and memories may carry no site (director/operator rows): the author may still write and read them.
    v_nullable := r.tbl in ('telemetry', 'memories');
    if r.site_kind = 'one' then
      v_site := format('%I = (select steward.agent_site())', r.site_col);
      if v_nullable then
        v_site := format('(%I is null or %s)', r.site_col, v_site);
      end if;
    elsif r.site_kind = 'many' then
      v_site := format('coalesce(%I ? (select steward.agent_site()), false)', r.site_col);
    else
      v_site := 'true';
    end if;

    if r.site_kind = 'none' then
      v_read := '(select steward.agent_id()) is not null';
    else
      v_read := format('(select steward.agent_id()) is not null and ((select steward.agent_is_global()) or %s)', v_site);
      if r.bind_col is not null then
        v_read := format('(%s or %I = (select steward.agent_id()))', v_read, r.bind_col);
      end if;
    end if;
    execute format('create policy %I on public.%I for select to authenticated using (%s)', 'steward read', r.tbl, v_read);
    execute format('grant select on public.%I to authenticated', r.tbl);

    if cardinality(r.writers) > 0 then
      v_write := format('(select steward.agent_role()) = any (%L::text[]) and ((select steward.agent_is_global()) or %s)', r.writers, v_site);
      if r.bind_col is not null then
        v_write := format('%s and %I = (select steward.agent_id())', v_write, r.bind_col);
      end if;
      if r.extra_check is not null then
        v_write := format('%s and (%s)', v_write, r.extra_check);
      end if;
      execute format('create policy %I on public.%I for insert to authenticated with check (%s)', 'steward write', r.tbl, v_write);
      execute format('grant insert on public.%I to authenticated', r.tbl);
      if not r.append_only then
        execute format('create policy %I on public.%I for update to authenticated using (%s) with check (%s)', 'steward update', r.tbl, v_write, v_write);
        execute format('grant update on public.%I to authenticated', r.tbl);
      end if;
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- anon: SELECT on four non-sensitive tables only. Nothing with people, contact details, transcripts or document text.
-- ---------------------------------------------------------------------------------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array['facts', 'eye_frames', 'findings', 'maintenance_windows'] loop
    execute format('drop policy if exists %I on public.%I', 'steward public read', t);
    execute format('create policy %I on public.%I for select to anon using (true)', 'steward public read', t);
    execute format('grant select on public.%I to anon', t);
  end loop;
end $$;

-- Sequences and functions in public stay private unless granted below or in later migrations.
revoke all on all sequences in schema public from anon, authenticated;

-- ---------------------------------------------------------------------------------------------------------------
-- Authority probe for POST /api/supabase/authority-check: attempts the write as the calling agent (SECURITY INVOKER,
-- so RLS and privileges apply exactly as they would to a real upsert), captures Postgres's own refusal, and always
-- rolls back, so a probe can never leave a row behind (attestations are append-only).
-- ---------------------------------------------------------------------------------------------------------------
create or replace function public.steward_authority_tables() returns setof text
language sql stable security definer set search_path = ''
as $$ select tbl from steward.authority $$;

create or replace function public.steward_authority_probe(p_table text, p_action text, p_site text default null)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_state  text;
  v_msg    text;
  v_detail text;
  v_hint   text;
  v_id     text := 'probe-' || replace(gen_random_uuid()::text, '-', '');
  v_site   text := coalesce(p_site, 'myer-plant');
  v_rows   bigint;
begin
  if p_table not in (select t from public.steward_authority_tables() as t) then
    return jsonb_build_object('attempted', false, 'reason', 'unknown table');
  end if;
  begin
    if p_action = 'insert' then
      if p_table = 'attestations' then
        insert into public.attestations (id, property_id, asset_tag, attribute, value, verdict, source, verifier_version, signed_at)
        values (v_id, v_site, 'P-101', 'pressure_bar', '3.2'::jsonb, 'accepted', '{"kind":"human","ref":"authority-probe"}'::jsonb, 'steward-verify/1', now());
      elsif p_table = 'facts' then
        insert into public.facts (id, property_id, asset_tag, attribute, value, observed_at) values (v_id, v_site, 'P-101', 'pressure_bar', '3.2'::jsonb, now());
      elsif p_table = 'obligations' then
        insert into public.obligations (id, site_id, title, status) values (v_id, v_site, 'authority probe', 'ok');
      elsif p_table = 'work_items' then
        insert into public.work_items (id, property_id, asset_tag, attribute, state) values (v_id, v_site, 'P-101', 'pressure_bar', 'open');
      elsif p_table = 'dispatches' then
        insert into public.dispatches (id, property_id, channel, body) values (v_id, v_site, 'local', 'authority probe');
      elsif p_table = 'issues' then
        insert into public.issues (id, site_id, kind, severity, status, summary) values (v_id, v_site, 'probe', 'low', 'open', 'authority probe');
      elsif p_table = 'changes' then
        insert into public.changes (id, property_id, version, type, summary, at) values (v_id, v_site, -1, 'probe', 'authority probe', now());
      elsif p_table = 'crew_members' then
        insert into public.crew_members (id, site_id, name) values (v_id, v_site, 'authority probe');
      elsif p_table = 'maintenance_windows' then
        insert into public.maintenance_windows (id, site_ids, scope, status) values (v_id, jsonb_build_array(v_site), 'authority probe', 'proposed');
      elsif p_table = 'notifications' then
        insert into public.notifications (id, site_id, sender, text) values (v_id, v_site, (select steward.agent_id()), 'authority probe');
      elsif p_table = 'eye_frames' then
        insert into public.eye_frames (id, site_id, actor, action) values (v_id, v_site, (select steward.agent_id()), 'look');
      elsif p_table = 'findings' then
        insert into public.findings (id, site_id, asset_tag, status) values (v_id, v_site, 'V-501', 'uncertain');
      elsif p_table = 'telemetry' then
        insert into public.telemetry (id, site_id, agent_id, kind) values (v_id, v_site, (select steward.agent_id()), 'probe');
      elsif p_table = 'memories' then
        insert into public.memories (id, site_id, agent_id, kind, content) values (v_id, v_site, (select steward.agent_id()), 'note', 'authority probe');
      elsif p_table = 'conversations' then
        insert into public.conversations (id, site_ids, convener, kind, topic) values (v_id, jsonb_build_array(v_site), (select steward.agent_id()), 'message', 'authority probe');
      elsif p_table = 'viewer_commands' then
        insert into public.viewer_commands (id, site_id, issued_by, action) values (v_id, v_site, (select steward.agent_id()), 'reset');
      elsif p_table = 'subscriptions' then
        insert into public.subscriptions (id, property_id, callback_url, requester) values (v_id, v_site, 'https://example.invalid/cb', 'authority-probe');
      elsif p_table = 'agents' then
        insert into public.agents (id, level, role, display_name) values (v_id, 5, 'technician', 'authority probe');
      end if;
    elsif p_action in ('update', 'delete') then
      if p_table = 'agents' then
        execute format('%s public.agents %s where id = %L', case p_action when 'update' then 'update' else 'delete from' end,
                       case p_action when 'update' then 'set display_name = display_name' else '' end, 'operator');
      else
        execute format(case p_action
                         when 'update' then 'update public.%I set id = id where id in (select id from public.%I order by id limit 1)'
                         else 'delete from public.%I where id in (select id from public.%I order by id limit 1)' end,
                       p_table, p_table);
      end if;
    else
      return jsonb_build_object('attempted', false, 'reason', 'action must be insert, update or delete');
    end if;
    get diagnostics v_rows = row_count;
    raise exception using errcode = 'P0001', message = 'steward-authority-probe-rollback', detail = v_rows::text;
  exception
    when others then
      get stacked diagnostics v_state = returned_sqlstate, v_msg = message_text, v_detail = pg_exception_detail, v_hint = pg_exception_hint;
      if v_msg = 'steward-authority-probe-rollback' then
        return jsonb_build_object('attempted', true, 'allowed', true, 'rowsAffected', v_detail::bigint, 'rolledBack', true,
                                  'note', case when v_detail = '0' and p_action <> 'insert'
                                               then 'no row was visible to this agent, so nothing would change' end);
      end if;
      return jsonb_build_object('attempted', true, 'allowed', false, 'sqlstate', v_state, 'message', v_msg, 'detail', nullif(v_detail, ''),
                                'hint', nullif(v_hint, ''), 'rolledBack', true);
  end;
end
$$;

revoke all on function public.steward_authority_probe(text, text, text) from public, anon;
grant execute on function public.steward_authority_probe(text, text, text) to authenticated, service_role;
revoke all on function public.steward_authority_tables() from public, anon;
grant execute on function public.steward_authority_tables() to authenticated, service_role;
