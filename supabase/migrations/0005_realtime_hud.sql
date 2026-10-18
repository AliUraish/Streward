-- 0005_realtime_hud.sql: Realtime Authorization for the live HUD. Idempotent.
--
-- Private channels `site:<siteId>:hud` (the site must be one of the agents' sites). Policies on realtime.messages:
--   * SELECT (receive Broadcast, listen to Presence): anon and authenticated, on hud topics only;
--   * INSERT with extension 'presence' (track): anon and authenticated, on hud topics only, so a viewer can say it is
--     watching; there is NO insert policy for 'broadcast', so no browser can send HUD events or spoof one.
-- The backend sends HUD events through the Realtime broadcast REST endpoint with the secret key (service role), the
-- only sender. Public channels with the same name are separate (Supabase: "a private broadcast only reaches private
-- channels"), so nothing sent on a public channel can reach a HUD subscriber.

create or replace function steward.hud_topic_ok(p_topic text) returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(p_topic ~ '^site:[a-z0-9-]{3,40}:hud$'
                  and split_part(p_topic, ':', 2) in (select a.site_id from public.agents a where a.site_id is not null), false)
$$;

revoke all on function steward.hud_topic_ok(text) from public;
grant usage on schema steward to anon, authenticated;
grant execute on function steward.hud_topic_ok(text) to anon, authenticated, service_role;

drop policy if exists "steward hud receive" on realtime.messages;
create policy "steward hud receive" on realtime.messages
  for select
  to anon, authenticated
  using (realtime.messages.extension in ('broadcast', 'presence') and (select steward.hud_topic_ok((select realtime.topic()))));

drop policy if exists "steward hud presence" on realtime.messages;
create policy "steward hud presence" on realtime.messages
  for insert
  to anon, authenticated
  with check (realtime.messages.extension = 'presence' and (select steward.hud_topic_ok((select realtime.topic()))));
