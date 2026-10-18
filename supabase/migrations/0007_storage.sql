-- 0007_storage.sql: private buckets for eye frames and evidence, and the usage RPCs the budget guard polls. Idempotent.
--
-- Only the backend writes (secret key = service role, which bypasses RLS); browsers only ever read through signed URLs
-- (15 minutes). There is deliberately no permissive policy on storage.objects for these buckets, and a RESTRICTIVE
-- policy keeps them closed to anon and authenticated even if a permissive policy is added later.
-- file_size_limit is the larger plan default (10 MB); the backend enforces SUPABASE_CAP_UPLOAD_MB before uploading.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('eye-frames', 'eye-frames', false, 10485760, array['image/jpeg']),
  ('evidence',   'evidence',   false, 10485760, array['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'application/pdf',
                                                        'text/plain', 'application/json', 'application/octet-stream'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

do $$
begin
  drop policy if exists "steward buckets are backend only" on storage.objects;
  create policy "steward buckets are backend only" on storage.objects
    as restrictive
    for all
    to anon, authenticated
    using (bucket_id not in ('eye-frames', 'evidence'))
    with check (bucket_id not in ('eye-frames', 'evidence'));
exception
  when insufficient_privilege then
    raise notice 'storage.objects policy not created (not the owner); the buckets stay private by default';
end $$;

-- Usage RPCs (secret key only): database size and our buckets' bytes, polled every 10 minutes by the budget guard.
create or replace function public.steward_db_size() returns bigint
language sql
stable
security definer
set search_path = ''
as $$ select pg_database_size(current_database()) $$;

create or replace function public.steward_storage_usage() returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(jsonb_object_agg(b.id, jsonb_build_object('objects', coalesce(u.objects, 0), 'bytes', coalesce(u.bytes, 0))), '{}'::jsonb)
  from storage.buckets b
  left join (
    select o.bucket_id, count(*) as objects, sum(coalesce((o.metadata ->> 'size')::bigint, 0)) as bytes
    from storage.objects o
    where o.bucket_id in ('eye-frames', 'evidence')
    group by o.bucket_id
  ) u on u.bucket_id = b.id
  where b.id in ('eye-frames', 'evidence')
$$;

revoke all on function public.steward_db_size() from public, anon, authenticated;
revoke all on function public.steward_storage_usage() from public, anon, authenticated;
grant execute on function public.steward_db_size() to service_role;
grant execute on function public.steward_storage_usage() to service_role;

-- Every function this build added to public is private unless granted on purpose (Supabase's default privileges grant
-- EXECUTE on new public functions to anon and authenticated).
do $$
declare
  f regprocedure;
begin
  for f in
    select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'steward\_%' or p.proname like 'inkbox\_%' or p.proname = 'verify_ledger')
  loop
    execute format('revoke execute on function %s from public, anon', f);
  end loop;
end $$;
grant execute on function public.verify_ledger(bigint, text), public.steward_ledger_head(),
  public.steward_authority_probe(text, text, text), public.steward_authority_tables() to authenticated;
