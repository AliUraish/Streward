-- Steward seed: the three demonstration sites from backend/src/seed.py.
-- Facts, attestations and work items are NOT seeded here: they carry Ed25519
-- signatures produced by the backend's key, and the mirror must only contain
-- rows the backend actually signed. Run `backend/scripts/supabase-sync.py`
-- (backend stream) to backfill those from SQLite.
insert into public.properties (id, name, address, phase) values
  ('myer-plant',   'Myer Plant Room',       'Kenneth Myer Building plant room (SuperSplat capture)', 'operational'),
  ('harbor-works',  'Harbor Works',      'Harbor Way, Oakland (fixture twin)', 'restart pending'),
  ('bristol-pumps', 'Bristol Dock Machine Room', 'Bristol Docks pump house (SuperSplat capture)', 'under restoration')
on conflict (id) do update
  set name = excluded.name, address = excluded.address, phase = excluded.phase;
