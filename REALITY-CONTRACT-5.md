> RESTORED by the user on Oct 18 2026 at 00:50 PDT (briefly withdrawn at 00:40). Active.

# Contract addendum 5: the third site, Tomioka Silk Mill

Written Oct 18 2026, 00:05 PDT. Extends contracts 3 and 4; everything there stands. Same rules: no git commands that change state, no paid calls, never kill processes by pattern, do not restart the dev stack on 3000/8001/8002 (the orchestrator does), test servers only on your own ports started and stopped by PID.

## 1. The site

| field | value |
| --- | --- |
| id | `tomioka-mill` |
| reference prefix | TM |
| name | Tomioka Silk Mill |
| site line | 富岡製糸場, Tomioka, Gunma Prefecture, Japan (UNESCO World Heritage; buildings designated National Treasures) |
| operator | demo operator (do not imply the real site operator uses Steward) |
| status | open to visitors |
| kind | heritage industrial site; an 1872 silk reeling mill preserved with its reeling machines |
| jurisdiction | `JP` (Japan, Gunma) |
| scan | SuperSplat 849bce2a, "富岡製糸場" by **acrylagitt**, 271.06 MB, streamed LOD |
| content URL | `https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/lod-meta.json` (LOD v1: count 23,564,860 across 5 levels, 44 chunk files, octree `tree`; `access-control-allow-origin: *`) |
| embed | `https://superspl.at/s?id=849bce2a` |
| thumbnail | `https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/849bce2a/v1/xl.webp` |
| initial camera | position [-32.414, 0.287, -43.351], target [-33.558, 0.001, -44.495], fov 75 (scratchpad `splat/settings-849bce2a.json`) |
| credit | "富岡製糸場 by acrylagitt on SuperSplat", captureNote as for the other splat sites |

Scratchpad = `/private/tmp/claude-501/-Users-aliuraishmirani-YC-Hackstripe/bd5a4097-1616-4efe-92a2-5c2361139e1c/scratchpad`. Load from the CloudFront origin at runtime; never copy the capture.

Every place that enumerates sites gains `tomioka-mill`: backend registry and enums, MCP `PROPERTY_IDS`, frontend site lists and switchers, Supabase `agents`/RLS data, eval suites where sites are listed, `shared/types.ts` (`SiteId`, updated by the orchestrator; the MCP keeps its verbatim schema copy in sync).

## 2. Team (Inkbox identities already created, with A2A skills, keys and webhooks)

| level | id | display name | Inkbox handle | env suffix |
| --- | --- | --- | --- | --- |
| 3 | `tomioka-manager` | Site Manager · Tomioka | steward-tomioka-manager | TOMIOKA_MANAGER |
| 4 | `tomioka-engineer` | Conservation Engineer · Tomioka | steward-tomioka-engineer | TOMIOKA_ENGINEER |
| 4 | `tomioka-compliance` | Compliance Officer · Tomioka | steward-tomioka-compliance | TOMIOKA_COMPLIANCE |
| 5 | `tomioka-technician` | Field Technician · Tomioka | steward-tomioka-technician | TOMIOKA_TECHNICIAN |

Authority exactly as the other sites' roles (manager, engineer, compliance, technician), scope `tomioka-mill`. The Director's scope becomes all three sites. Cross-site messages: manager to manager, compliance to compliance, anyone to or from the director.

## 3. Asset register (24; the PINS stream maps each tag to a visible object later)

| tags | kind | name |
| --- | --- | --- |
| RM-101 … RM-106 | machine | Automatic silk reeling machines, rows 1 to 6 |
| TR-201 … TR-204 | structure | Wooden king-post roof trusses, bays 1 to 4 |
| BW-251 | structure | Brick wall, east elevation (National Treasure fabric) |
| HS-301 … HS-303 | sensor | Humidity and temperature sensors, north, centre, south |
| VS-401 | sensor | Seismic and vibration sensor |
| FE-501 … FE-503 | fire | Portable fire extinguishers |
| FH-601 | hydrant | Indoor fire hydrant |
| D-701, D-702 | door | Visitor emergency exits |
| W-801 | walkway | Visitor walkway and barrier |
| EP-901 | panel | Electrical distribution panel |
| CC-1001 | camera | Conservation CCTV camera |
| DH-1101 | dehumidifier | Mobile dehumidifier |

Specs for new kinds (add to specs.py): machine `vibration_mms` reading 0–4.5, `status` condition enum running/stopped/fault; structure `crack_width_mm` reading 0–0.3, `condition` enum sound/watch/defect; sensor (humidity) `humidity_pct` reading 40–65 for preservation plus `temperature_c` 5–30; seismic sensor `seismic_gal` reading 0–80; hydrant `pressure_ok` enum yes/no; camera `working` yes/no; dehumidifier `running` yes/no. Existing kinds keep their specs.

Metrics for this site: `humidity_pct`, `temperature_c`, `visitor_count` (per hour, 0 outside opening hours), `vibration_mms`, `crack_width_mm`, `power_kw`, with the same generator rules (seeded, labelled synthetic, scenario overlays, live points while simulation is on).

## 4. Crew (synthetic, Japanese names, no contact details except the duty engineer, who is the user)

Site manager on duty, conservation architect, conservator for the reeling machines, visitor safety lead, fire and facilities officer, guide supervisor; plus "Duty engineer (you)" as on the other sites. Ownership of issue kinds as on the other sites, plus `humidity_high` and `alteration_permit` (conservation architect) and `visitor_route` (visitor safety lead).

## 5. Scenarios

| id | what happens | owners |
| --- | --- | --- |
| `tm-humidity` (headline) | After a typhoon, relative humidity in the Silk Reeling Mill reaches 88 % and rises; mould risk to the wooden trusses TR-201…TR-204 and the reeling machines; the Conservation Engineer raises it, calls the Site Manager, the Compliance Officer cites the cultural-property management duty, the technician sends the conservator to start DH-1101 and close the north windows; humidity returns under 65 %; the engineer verifies through the eye and signs. | Conservation Engineer, conservator |
| `tm-alteration-permit` | A contractor's work order proposes drilling brackets for new sensors into the brick wall BW-251 (National Treasure fabric). The Compliance Officer blocks it: altering the current state of a designated property needs permission from the Commissioner for Cultural Affairs. The manager chooses a non-invasive clamp mount instead and files the permit request for the rest. | Compliance Officer, conservation architect |
| `x-heritage` (cross-site) | Tomioka's Compliance Officer asks Bristol's (both heritage sites open to visitors) how Bristol mounts sensors on its 1907 pumps without altering historic fabric and how it closes a visitor route during a hazard; the two managers agree to share the clamp-mount method and the route-closure procedure; the Director approves; a shared `maintenance_window` (scope: heritage-safe sensor installation) appears on both sites. | both compliance officers and managers, Director |

Every scenario follows the contract-4 fix workflow and conversation rules: conversations with summaries, notifications, signed proofs, labelled synthetic, nothing fires until started.

## 6. Regulations (Japan)

Official sources only, cached in `backend/data/regulations/`, records appended to `backend/seed/regulations/regulations.json` with `jurisdiction: 'JP'` and `siteIds: ['tomioka-mill']`:
- Act on Protection of Cultural Properties (文化財保護法, Act No. 214 of 1950): management duties for designated properties, and restrictions on altering the current state of Important Cultural Properties (including National Treasures) and Historic Sites.
- Fire Service Act (消防法, Act No. 186 of 1948): fire-fighting equipment installation and maintenance, and periodic inspection and reporting.
- Industrial Safety and Health Act (労働安全衛生法, Act No. 57 of 1972) only if a scenario needs worker-safety duties.
Sources: e-Gov法令検索 (laws.e-gov.go.jp) for the Japanese text and Japanese Law Translation (japaneselawtranslation.go.jp) for English. Record the exact licence/terms text of each site verbatim and set `servePdf` by those terms. Summaries are our own English, with the Japanese article number (for example 第43条) alongside the English reference. Provision numbers must be confirmed against the downloaded text.
