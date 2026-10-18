"""Original demonstration specifications and observations, never statutory certification."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .store import Store, now

ROOT = Path(__file__).resolve().parents[2]
SCENE = json.loads((ROOT / "shared" / "scene.json").read_text())
PROPERTIES = [
    ("cedar", "Cedar House", "1840 Cedar Street, San Francisco", "Commissioning"),
    ("harbor", "Harbor Works", "68 Harbor Way, Oakland", "Fit-out"),
    ("juniper", "Juniper Residence", "215 Juniper Avenue, San Jose", "Handover"),
]
CHECKS = [
    ("ID", "Equipment identification", "Asset tag must be present and unique in the project scene register."),
    ("LOC", "Model location", "The registered component origin must lie inside the plant-room model bounds."),
    ("DOC", "Commissioning record", "A machine-readable project commissioning record must reference this property and exact asset tag."),
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


def seed(store: Store):
    if store.meta("seed_version") == "1":
        return

    def insert(kind, body, property_id=""):
        if not store.get(kind, body["id"], property_id):
            store.put(kind, body, property_id)

    for index, (property_id, name, address, phase) in enumerate(PROPERTIES):
        inserted_at = now()
        insert("property", dict(id=property_id, name=name, address=address,
                                jurisdiction="California / demonstration project", phase=phase,
                                readiness=0, componentCount=len(SCENE["components"]), openIssues=0,
                                updatedAt=inserted_at))
        documents = []
        for suffix, title, category, sections in [
            ("spec", "Mechanical & Electrical Project Requirements", "Project specifications", [
                (f"{code} - {check_title}", [description, "", "Applies to the following registered project assets:"] +
                 [f"{component['tag']}  |  {component['name']}" for component in SCENE["components"]])
                for code, check_title, description in CHECKS
            ]),
            ("register", "Plant Room Asset Register", "Equipment schedules", [
                ("Mechanical systems", [f"Property ID: {property_id}", "Plant room: 13 m x 12 m x 4.6 m.", ""] +
                 [f"{c['tag']} - {c['name']}" for c in SCENE["components"] if c["system"] == "Mechanical"]),
                ("Electrical and access systems", [f"Property ID: {property_id}", ""] +
                 [f"{c['tag']} - {c['name']}" for c in SCENE["components"] if c["system"] != "Mechanical"]),
            ]),
            ("observations", "Baseline Commissioning Observations", "Inspection records", [
                ("Synthetic baseline - equipment observations", [
                    f"Property ID: {property_id}",
                    "This is synthetic fixture evidence used to demonstrate the local workflow.",
                    "A green state means project evidence checks passed; it is not legal certification.", "",
                ] + [f"{c['tag']} - baseline: {c['status'].upper()}" for c in SCENE["components"]]),
            ]),
        ]:
            doc_id = f"{property_id}-{suffix}"
            filename = f"{property_id}-{suffix}.pdf"
            file_path = store.directory / "files" / filename
            if not file_path.exists():
                write_pdf(file_path, title, sections, name)
            text = "\n\n".join(heading + "\n" + "\n".join(lines) for heading, lines in sections)
            body = dict(id=doc_id, title=title, filename=filename, category=category,
                        jurisdiction="Demo project specification", pages=len(sections), size=file_path.stat().st_size,
                        uploadedAt=inserted_at, url=f"/api/documents/{doc_id}/file", extractedText=text,
                        _path=filename, _propertyId=property_id)
            insert("document", body, property_id)
            documents.append(body)
        for number, template in enumerate(SCENE["components"]):
            component = deepcopy(template)
            # Each property has its own persisted record, even when the geometry is shared.
            if property_id == "harbor" and number % 7 == 0:
                component["status"] = "pending"
            if property_id == "juniper" and number % 9 == 0:
                component["status"] = "issue"
            initial_status = component["status"]
            component["requirementCount"] = 4
            component["verifiedCount"] = 4 if initial_status == "verified" else 2
            insert("component", component, property_id)
            for check_index, (code, title, description) in enumerate(CHECKS):
                requirement_id = f"{property_id}-{component['id']}-{code.lower()}"
                status = "verified" if check_index < 2 or initial_status == "verified" else (
                    "issue" if check_index == 3 and initial_status == "issue" else "pending")
                evidence = (
                    "Scene register contains a unique project tag." if check_index == 0 else
                    "Registered origin is within the plant-room model bounds." if check_index == 1 else
                    "Synthetic commissioning record references this property and asset." if status == "verified" else
                    "Synthetic baseline records an unresolved condition observation." if status == "issue" else
                    "Required machine-readable record has not been supplied."
                )
                insert("requirement", dict(id=requirement_id, code=f"PRJ-{code}-{number + 1:03d}", title=title,
                    description=description, system=component["system"], componentId=component["id"], status=status,
                    sourceId=f"{property_id}-spec", sourceTitle=documents[0]["title"], sourcePage=check_index + 1,
                    evidence=evidence, _check=code), property_id)
                if check_index > 1 and status in ("verified", "issue"):
                    outcome = "fail" if status == "issue" else "pass"
                    evidence_id = f"seed-{requirement_id}"
                    filename = f"{evidence_id}.json"
                    payload = dict(propertyId=property_id, componentId=component["id"], tag=component["tag"],
                                   requirementId=requirement_id, outcome=outcome, synthetic=True,
                                   note="Original synthetic baseline observation for this local demonstration.")
                    (store.directory / "files" / filename).write_text(json.dumps(payload, indent=2))
                    insert("evidence", dict(id=evidence_id, componentId=component["id"], requirementId=requirement_id,
                        filename=filename, note=payload["note"], status=status, createdAt=inserted_at,
                        url=f"/api/evidence/{evidence_id}/file", _path=filename, _assessment=payload,
                        _text=json.dumps(payload), _propertyId=property_id), property_id)
        insert("memory", dict(id=f"{property_id}-initial-memory", propertyId=property_id,
            content=f"{name} is an original demonstration property. Baseline observations are synthetic. "
                    "Use exact asset tags and property IDs when checking evidence; a matching filename alone is insufficient.",
            source="Local project initialization", createdAt=inserted_at), property_id)
        insert("chat", dict(id=f"{property_id}-welcome", role="assistant", createdAt=inserted_at,
            content=f"I'm {name}'s local property agent. I can inspect the project register, trace requirements to source pages, "
                    "check uploaded evidence, remember findings and prepare a report. Local checks are deterministic; "
                    "model-backed synthesis activates when a model provider is configured. What would you like to inspect?",
            sources=[]), property_id)
        if not store.events(property_id):
            store.event(property_id, f"agent-{property_id}", "project.created", "Property workspace initialized",
                        "24 original scene objects and 96 project checks loaded with clearly labeled synthetic baseline evidence.")
    insert("agent", dict(id="portfolio", name="Steward Coordinator", role="Steward portfolio coordinator", status="idle",
        identity="local://steward/agents/portfolio", lastAction="Ready to compare property readiness and coordinate inspection jobs.",
        tools=["list_properties", "get_portfolio", "run_inspection", "get_job", "export_report"]))
    for property_id, name, _, _ in PROPERTIES:
        insert("agent", dict(id=f"agent-{property_id}", name=f"Steward {property_id.title()}",
            role=f"{name} property agent", status="idle", identity=f"local://steward/agents/{property_id}",
            lastAction="Project context loaded. Awaiting an inspection or instruction.",
            tools=["inspect_component", "search_requirements", "search_documents", "assess_evidence", "recall_memory", "save_memory", "export_report"]))
    store.meta("seed_version", "1")
