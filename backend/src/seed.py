"""Original demonstration specifications and observations, never statutory certification."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .registers import register_for, room_for
from .sites import SITES, property_record
from .store import Store, now

ROOT = Path(__file__).resolve().parents[2]
PROPERTIES = [(site["id"], site["name"]) for site in SITES]
REGISTER_VERSION = "3"
SITES_VERSION = "5"  # contract 5: the third site (tomioka-mill) is seeded into existing databases by add_new_sites
HERITAGE_SYSTEMS = ("Heritage machinery", "Structure", "Conservation")
CHECKS = [
    ("ID", "Equipment identification", "Asset tag must be present and unique in the project scene register."),
    ("LOC", "Model location", "The registered component origin must lie inside the plant-room model bounds."),
    ("DOC", "Commissioning record", "A machine-readable project commissioning record must reference this site and exact asset tag."),
    ("COND", "Recorded condition", "The baseline observation must contain a passing condition result for this exact asset. Fixture evidence is not a physical inspection."),
]


def write_pdf(path: Path, title: str, sections: list[tuple[str, list[str]]], property_name: str):
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(title)
    pdf.setAuthor("Steward local demonstration")
    width, height = A4
    for page, (heading, lines) in enumerate(sections, 1):
        pdf.setFillColor(colors.HexColor("#172f2b"))
        pdf.rect(0, height - 105, width, 105, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(42, height - 38, "STEWARD / PROJECT EVIDENCE")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(42, height - 61, property_name)
        pdf.setFont("Helvetica-Bold", 17)
        pdf.drawString(42, height - 87, heading[:65])
        pdf.setFillColor(colors.HexColor("#a34822"))
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(42, height - 132, "DEMONSTRATION PROJECT SPECIFICATION - NOT A BUILDING CODE")
        pdf.setFillColor(colors.HexColor("#303b39"))
        pdf.setFont("Helvetica", 10)
        y = height - 158
        for line in lines:
            # Wrap deterministically without relying on PDF layout inference.
            while len(line) > 92:
                boundary = line.rfind(" ", 0, 92)
                boundary = boundary if boundary > 0 else 92
                pdf.drawString(42, y, line[:boundary])
                line = line[boundary:].strip()
                y -= 15
            pdf.drawString(42, y, line)
            y -= 18
        pdf.setStrokeColor(colors.HexColor("#d5dedb"))
        pdf.line(42, 49, width - 42, 49)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(42, 34, "Original synthetic data. No real property, site visit or regulatory approval is represented.")
        pdf.drawRightString(width - 42, 34, str(page))
        pdf.showPage()
    pdf.save()


def seed_documents(store: Store, site: dict, components: list[dict], inserted_at: str, overwrite: bool = False) -> list[dict]:
    """The three seed PDFs (requirements, register, baseline observations) generated from the site's own register."""
    property_id, name = site["id"], site["name"]
    room = room_for(property_id)
    documents = []
    # The heritage mill (contract 5) has no "Mechanical" plant; its register groups machinery, structure and conservation.
    heritage = any(c["system"] in HERITAGE_SYSTEMS for c in components)
    primary = ("Mechanical",) + (HERITAGE_SYSTEMS if heritage else ())
    area = site.get("area") or "plant room"
    for suffix, title, category, sections in [
        ("spec", "Mechanical & Electrical Project Requirements", "Project specifications", [
            (f"{code} - {check_title}", [description, "", "Applies to the following registered project assets:"] +
             [f"{component['tag']}  |  {component['name']}" for component in components])
            for code, check_title, description in CHECKS
        ]),
        ("register", "Site Asset Register" if heritage else "Plant Room Asset Register", "Equipment schedules", [
            ("Machinery, structure and conservation" if heritage else "Mechanical systems",
             [f"Site ID: {property_id}", (f"{area[:1].upper()}{area[1:]} (register section): " if heritage else "Plant room: ")
              + f"{room['width']} m x {room['depth']} m x {room['height']} m.", ""] +
             [f"{c['tag']} - {c['name']}" for c in components if c["system"] in primary]),
            ("Fire, electrical, security and access" if heritage else "Electrical and access systems", [f"Site ID: {property_id}", ""] +
             [f"{c['tag']} - {c['name']}" for c in components if c["system"] not in primary]),
        ]),
        ("observations", "Baseline Commissioning Observations", "Inspection records", [
            ("Synthetic baseline - equipment observations", [
                f"Site ID: {property_id}",
                "This is synthetic fixture evidence used to demonstrate the local workflow.",
                "A green state means project evidence checks passed; it is not legal certification.", "",
            ] + [f"{c['tag']} - baseline: {c['status'].upper()}" for c in components]),
        ]),
    ]:
        doc_id = f"{property_id}-{suffix}"
        filename = f"{property_id}-{suffix}.pdf"
        file_path = store.directory / "files" / filename
        if overwrite or not file_path.exists():
            write_pdf(file_path, title, sections, name)
        text = "\n\n".join(heading + "\n" + "\n".join(lines) for heading, lines in sections)
        body = dict(id=doc_id, title=title, filename=filename, category=category,
                    jurisdiction="Demo project specification", pages=len(sections), size=file_path.stat().st_size,
                    uploadedAt=inserted_at, url=f"/api/documents/{doc_id}/file", extractedText=text,
                    _path=filename, _propertyId=property_id)
        if overwrite or not store.get("document", doc_id, property_id):
            existing = store.get("document", doc_id, property_id)
            if existing:
                body["uploadedAt"] = existing.get("uploadedAt", inserted_at)
            store.put("document", body, property_id)
        documents.append(store.get("document", doc_id, property_id))
    return documents


def seed_component(store: Store, property_id: str, component: dict, documents: list[dict], inserted_at: str) -> None:
    """Insert one register component with its four project checks and synthetic baseline evidence (insert-if-missing)."""
    def insert(kind, body):
        if not store.get(kind, body["id"], property_id):
            store.put(kind, body, property_id)

    number = next((index for index, c in enumerate(register_for(property_id)) if c["id"] == component["id"]), 0)
    initial_status = component["status"]
    component = deepcopy(component)
    component["requirementCount"] = 4
    component["verifiedCount"] = 4 if initial_status == "verified" else 2
    insert("component", component)
    for check_index, (code, title, description) in enumerate(CHECKS):
        requirement_id = f"{property_id}-{component['id']}-{code.lower()}"
        status = "verified" if check_index < 2 or initial_status == "verified" else (
            "issue" if check_index == 3 and initial_status == "issue" else "pending")
        evidence = (
            "Scene register contains a unique project tag." if check_index == 0 else
            "Registered origin is within the plant-room model bounds." if check_index == 1 else
            "Synthetic commissioning record references this site and asset." if status == "verified" else
            "Synthetic baseline records an unresolved condition observation." if status == "issue" else
            "Required machine-readable record has not been supplied."
        )
        insert("requirement", dict(id=requirement_id, code=f"PRJ-{code}-{number + 1:03d}", title=title,
            description=description, system=component["system"], componentId=component["id"], status=status,
            sourceId=f"{property_id}-spec", sourceTitle=documents[0]["title"], sourcePage=check_index + 1,
            evidence=evidence, _check=code))
        if check_index > 1 and status in ("verified", "issue"):
            outcome = "fail" if status == "issue" else "pass"
            evidence_id = f"seed-{requirement_id}"
            filename = f"{evidence_id}.json"
            payload = dict(propertyId=property_id, componentId=component["id"], tag=component["tag"],
                           requirementId=requirement_id, outcome=outcome, synthetic=True,
                           note="Original synthetic baseline observation for this local demonstration.")
            if not (store.directory / "files" / filename).exists() or not store.get("evidence", evidence_id, property_id):
                (store.directory / "files" / filename).write_text(json.dumps(payload, indent=2))
            insert("evidence", dict(id=evidence_id, componentId=component["id"], requirementId=requirement_id,
                filename=filename, note=payload["note"], status=status, createdAt=inserted_at,
                url=f"/api/evidence/{evidence_id}/file", _path=filename, _assessment=payload,
                _text=json.dumps(payload), _propertyId=property_id))


def _insert(store: Store, kind: str, body: dict, property_id: str = "") -> None:
    if not store.get(kind, body["id"], property_id):
        store.put(kind, body, property_id)


def seed_site(store: Store, site: dict) -> None:
    """One site's workspace (property, seed PDFs, register, checks, baseline evidence, memory, welcome, legacy agent);
    insert-if-missing, so it is safe on a database that already has part of it."""
    property_id, name = site["id"], site["name"]
    inserted_at = now()
    components = register_for(property_id)
    _insert(store, "property", property_record(site, len(components), inserted_at))
    documents = seed_documents(store, site, components, inserted_at)
    for component in components:
        seed_component(store, property_id, component, documents, inserted_at)
    _insert(store, "memory", dict(id=f"{property_id}-initial-memory", propertyId=property_id,
        content=f"{name} is an original demonstration site. Baseline observations are synthetic. "
                "Use exact asset tags and site IDs when checking evidence; a matching filename alone is insufficient.",
        source="Local project initialization", createdAt=inserted_at), property_id)
    _insert(store, "chat", dict(id=f"{property_id}-welcome", role="assistant", createdAt=inserted_at,
        content=f"I'm {name}'s site agent. I can inspect the project register, trace requirements to source pages, "
                "check uploaded evidence, remember findings and prepare a report. Local checks are deterministic; "
                "model-backed synthesis activates when a model provider is configured. What would you like to inspect?",
        sources=[]), property_id)
    if not store.events(property_id):
        store.event(property_id, f"agent-{property_id}", "project.created", "Site workspace initialized",
                    f"{len(components)} original register assets and {len(components) * len(CHECKS)} project checks loaded with clearly labeled synthetic baseline evidence.")
    _insert(store, "agent", dict(id=f"agent-{property_id}", name=f"Warden · {name}",
        role=f"{name} site agent", status="idle", identity=f"local://steward/agents/{property_id}",
        lastAction="Project context loaded. Awaiting an inspection or instruction.",
        tools=["inspect_component", "search_requirements", "search_documents", "assess_evidence", "recall_memory", "save_memory", "export_report"]))


def seed(store: Store):
    if store.meta("seed_version") == "1":
        return
    for site in SITES:
        seed_site(store, site)
    _insert(store, "agent", dict(id="portfolio", name="Atlas", role="Portfolio coordinator", status="idle",
        identity="local://steward/agents/portfolio", lastAction="Ready to compare site readiness and coordinate inspection jobs.",
        tools=["list_properties", "get_portfolio", "run_inspection", "get_job", "export_report"]))
    store.meta("seed_version", "1")
    store.meta("steward_register_version", REGISTER_VERSION)
    store.meta("steward_sites_version", SITES_VERSION)


def add_new_sites(store: Store) -> dict:
    """Contract 5: seed a site that joined the registry after the database was created (tomioka-mill), once
    (meta `steward_sites_version`), after a SQLite backup `pre-third-site-<stamp>`. Existing sites are untouched;
    seeding is insert-if-missing, so a re-run finds nothing to add and only re-sets the version marker."""
    if store.meta("steward_sites_version") == SITES_VERSION:
        return {}
    present = {p["id"] for p in store.all("property")}
    missing = [site for site in SITES if site["id"] not in present]
    if not missing:
        store.meta("steward_sites_version", SITES_VERSION)
        return {}
    from .sites import _backup
    backup = _backup(store, "pre-third-site") if present else None
    for site in missing:
        seed_site(store, site)
    store.meta("steward_sites_version", SITES_VERSION)
    return dict(added=[site["id"] for site in missing], backup=backup.name if backup else None)


ARCHIVE_ON_REGISTER_CHANGE = ("component", "requirement", "evidence")


def _archive(store: Store, kind: str, record: dict, property_id: str) -> None:
    with store.lock, store.connect() as db:
        db.execute("UPDATE records SET kind=?, property_id=? WHERE kind=? AND id=? AND property_id=?",
                   (f"archived:{kind}", f"archived-register:{property_id}", kind, record["id"], property_id))


def sync_registers(store: Store) -> dict:
    """Bring existing databases onto the per-site contract-3 registers, once (meta `steward_register_version`).

    Components whose ID is still registered are updated in place (name, tag, kind, layout, description; estimated
    pins replace 2-D pins unless an operator placed the pin). Components no longer registered are archived together
    with their checks and evidence (kind `archived:<kind>`), and so are facts and work items for tags that left the
    register; open missions waiting on such assets fail with an explicit reason. New components get their checks and
    synthetic baseline evidence, and the three seed PDFs are regenerated from the new register."""
    if store.meta("steward_register_version") == REGISTER_VERSION:
        return {}
    counts = dict(updated=0, added=0, archived=0, facts=0, workItems=0, missions=0)
    moment = now()
    for site in SITES:
        property_id = site["id"]
        if not store.get("property", property_id):
            continue
        register = register_for(property_id)
        wanted = {c["id"]: c for c in register}
        tags = {c["tag"] for c in register}
        existing = {c["id"]: c for c in store.all("component", property_id)}
        for component_id, component in existing.items():
            if component_id in wanted:
                continue
            _archive(store, "component", component, property_id)
            for kind in ("requirement", "evidence"):
                for record in store.all(kind, property_id):
                    if record.get("componentId") == component_id:
                        _archive(store, kind, record, property_id)
            counts["archived"] += 1
        for kind, key in (("fact", "facts"), ("work_item", "workItems")):
            for record in store.all(kind, property_id):
                if record.get("assetTag") not in tags:
                    _archive(store, kind, record, property_id)
                    counts[key] += 1
        for mission in store.all("mission", property_id):
            if mission.get("state") in ("running", "input_required") and any(i.get("assetTag") not in tags for i in mission.get("items", [])):
                mission.update(state="failed", phase="done", failure="Site register replaced (contract 3); the mission's assets are no longer registered.", updatedAt=moment)
                store.put("mission", mission, property_id)
                counts["missions"] += 1
        changed = any(component_id not in wanted for component_id in existing) or any(
            component_id not in existing or (existing[component_id].get("tag"), existing[component_id].get("name")) != (template["tag"], template["name"])
            for component_id, template in wanted.items())
        # Seed PDFs list the register, so they are regenerated only when the register's tags or names changed.
        documents = seed_documents(store, site, register, moment, overwrite=changed)
        for component_id, template in wanted.items():
            current = store.get("component", component_id, property_id)
            if current:
                placed = current.get("pinSource") == "placed" and isinstance(current.get("pin"), dict) and "z" in current["pin"]
                current.update({key: template[key] for key in ("tag", "name", "kind", "system", "subsystem", "position", "description")})
                if not placed:
                    current.update(pin=template["pin"], pinSource="estimated")
                store.put("component", current, property_id)
                counts["updated"] += 1
            else:
                seed_component(store, property_id, template, documents, moment)
                counts["added"] += 1
        prop = store.get("property", property_id)
        prop["componentCount"] = len(register)
        store.put("property", prop)
        store.event(property_id, f"agent-{property_id}", "register.synced", "Site register updated (contract 3)",
                    f"{counts['updated']} updated, {counts['added']} added, {counts['archived']} archived; pins are estimated until placed.")
    store.meta("steward_register_version", REGISTER_VERSION)
    return counts
