from __future__ import annotations

import html
import io
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pypdf import PdfReader

from .a2a import A2ABus
from .conversations import ConversationService
from .evalruns import EvalRunner
from .events import EventDirector
from .eye import EyeService
from .fixflow import FixWorkflowService
from .forge import ForgeService
from .integrations import ModelAdapter, SupermemoryAdapter
from .issues import IssueService
from .maintenance import MaintenanceService
from .maintenance_planner import MaintenancePlanner
from .compliance_gaps import ComplianceGaps
from .memory_store import MemoryStore
from .metrics import MetricsService
from .missions import MissionEngine
from .ops import OpsService
from .owner_notifications import OwnerNotifications
from .people import PeopleService
from .reality import RealityService
from .regulations import RegulationService
from .registers import room_for
from .autoplay import ScenarioAutoplay
from .patrol import PatrolService
from .scenarios import ScenarioEngine
from .seed import add_new_sites, seed, sync_registers
from .simulate import Simulator
from .sites import apply_site_shape
from .store import Store, now, uid
from .telemetry import Telemetry
from .viewer import ViewerService
from .vision import VisionIngest
from .waits import WaitHub
from .walks import WalkService
from .outbox import Outbox
from .voice_calls import VoiceCalls
from .chat_writer import ChatWriter
from .attendance import AttendanceService
from .inspections import InspectionService
from .demo_sequence import LiveSequence
from .agent_environment import AgentEnvironment
from .site_tours import SiteTourService


def public(value):
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [public(item) for item in value]
    return value


def extract_text(filename: str, data: bytes) -> tuple[str, int]:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > 300:
            raise ValueError("PDF exceeds the 300 page limit.")
        return "\n\f\n".join((page.extract_text() or "") for page in reader.pages), len(reader.pages)
    return data.decode("utf-8", errors="replace"), 1


class PropertyService:
    def __init__(self, data_directory: Path, start_workers: bool = True):
        self.store = Store(data_directory)
        seed(self.store)
        self.site_additions = add_new_sites(self.store)
        apply_site_shape(self.store)
        self.register_sync = sync_registers(self.store)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="steward-agent")
        self.submit_lock = threading.RLock()
        self.futures = {}
        self.start_workers = start_workers
        self.model = ModelAdapter()
        self.memory_adapter = SupermemoryAdapter()
        for prop in self.store.all("property"):
            self.recompute(prop["id"])
        if self.store.meta("steward_report_brand_version") != "1":
            for prop in self.store.all("property"):
                if (self.store.directory / "files" / f"{prop['id']}-report.html").exists():
                    self.write_report(prop["id"])
            self.store.meta("steward_report_brand_version", "1")
        self.telemetry = Telemetry(self)
        self.memory = MemoryStore(self)
        self.reality = RealityService(self, start_workers=start_workers)
        self.issues = IssueService(self)
        self.regulations = RegulationService(self)
        self.people = PeopleService(self)
        self.waits = WaitHub(self)
        self.reality.change_listeners.append(self.waits.on_change)
        self.bus = A2ABus(self)
        self.ops = OpsService(self)
        self.viewer = ViewerService(self)
        self.conversations = ConversationService(self)
        self.vision = VisionIngest(self)
        self.maintenance = MaintenanceService(self)
        self.eye = EyeService(self)
        self.metrics = MetricsService(self)
        self.fixes = FixWorkflowService(self)
        self.forge = ForgeService(self)
        self.missions = MissionEngine(self)
        self.scenarios = ScenarioEngine(self)
        self.patrols = PatrolService(self)  # contract 7: walkthroughs, labels and the compliance alerts they start
        self.walks = WalkService(self)  # each site's Engineer walks on its own; Claude looks at every stop (walks.py)
        self.autoplay = ScenarioAutoplay(self)
        self.simulator = Simulator(self)
        self.evals = EvalRunner(self)
        # Contract 7 §6 and the owner's maintenance ask: seeded compliance gaps (migration runs on every start) with a slow
        # drift, and the maintenance planner that books windows on its own and coordinates with the other sites.
        self.compliance_gaps = ComplianceGaps(self)
        self.maintenance_planner = MaintenancePlanner(self)
        # The owner's notifications page, the compliance snapshot PDF, the Operations Director's digest and the agents' play
        # reports, emailed to the owner on the owner channel (owner_notifications.py).
        self.owner = OwnerNotifications(self)
        # Random events at the sites (owner, Oct 18): Claude writes one every few minutes (templates when it cannot), validated and
        # played through the same services as the scenarios; the agents react as they already do (events.py).
        self.events = EventDirector(self)
        # Contract 8: one paced outbox for everything that reaches a person, real conversational phone calls, long agent chats
        # written by Claude, the employees' badge log with the People Officer, and the Site Inspector's inspection chain.
        self.outbox = Outbox(self)
        self.voice_calls = VoiceCalls(self)
        self.chats = ChatWriter(self)
        self.attendance = AttendanceService(self)
        self.inspections = InspectionService(self)
        # The agent environment (one read of a site as an agent sees it) and the Site Inspector's tours for any agent or MCP client.
        self.agent_environment = AgentEnvironment(self)
        self.site_tours = SiteTourService(self)
        # The owner's two-minute live sequence (demo_sequence.py): off unless STEWARD_LIVE_SEQUENCE=auto or POST /api/live-sequence.
        self.sequence = LiveSequence(self)
        if start_workers:
            self.recover_jobs()
            self.bus.start()
            self.missions.recover()
            self.simulator.start()
            self.autoplay.start()
            self.walks.start()
            self.compliance_gaps.start()
            self.maintenance_planner.start()
            self.owner.start()
            self.events.start()
            self.outbox.start()
            self.voice_calls.start()
            self.attendance.start()
            self.inspections.start()
            self.sequence.start()

    def close(self):
        self.sequence.close()
        self.site_tours.close()
        self.chats.close()
        self.inspections.close()
        self.attendance.close()
        self.voice_calls.close()
        self.outbox.close()
        self.events.close()
        self.owner.close()
        self.maintenance_planner.close()
        self.compliance_gaps.close()
        self.simulator.stop()
        self.autoplay.close()
        self.walks.close()
        self.scenarios.close()
        self.patrols.close()
        self.fixes.close()
        self.eye.close()
        self.missions.close()
        self.memory.close()
        self.bus.close()
        self.reality.close()
        self.executor.shutdown(wait=True)

    def require_property(self, property_id: str) -> dict:
        prop = self.store.get("property", property_id)
        if not prop:
            raise KeyError("Property not found.")
        return prop

    def component(self, property_id: str, component_id: str):
        self.require_property(property_id)
        component = self.store.get("component", component_id, property_id)
        if not component:
            raise KeyError("Component not found in this property.")
        return {**component,
                "requirements": [r for r in self.store.all("requirement", property_id) if r["componentId"] == component_id],
                "evidence": [e for e in self.store.all("evidence", property_id) if e["componentId"] == component_id]}

    def stats(self, property_id: str):
        requirements = self.store.all("requirement", property_id)
        return {**{status: sum(r["status"] == status for r in requirements) for status in ("verified", "pending", "issue", "unknown")},
                "total": len(requirements)}

    def recompute(self, property_id: str):
        requirements = self.store.all("requirement", property_id)
        for component in self.store.all("component", property_id):
            checks = [r for r in requirements if r["componentId"] == component["id"]]
            statuses = {r["status"] for r in checks}
            status = next((s for s in ("issue", "pending", "unknown") if s in statuses), "verified")
            component.update(status=status, requirementCount=len(checks), verifiedCount=sum(r["status"] == "verified" for r in checks))
            self.store.put("component", component, property_id)
        prop = self.require_property(property_id)
        stats = self.stats(property_id)
        prop.update(readiness=round(stats["verified"] / max(stats["total"], 1) * 100),
                    openIssues=stats["issue"], updatedAt=now())
        self.store.put("property", prop)

    def workspace(self, property_id: str):
        prop = self.require_property(property_id)
        active = [j for j in self.store.all("job", property_id) if j["status"] in ("queued", "running")]
        return dict(property=prop, components=self.store.all("component", property_id),
                    requirements=self.store.all("requirement", property_id), agents=self.agents(),
                    events=self.store.events(property_id)[-50:], activeJob=active[-1] if active else None,
                    stats=self.stats(property_id))

    def agents(self):
        agents = self.store.all("agent")
        jobs = [j for j in self.store.all("job") if j["status"] in ("running", "queued")]
        for agent in agents:
            matching = [job for job in jobs if agent["id"] == (
                "portfolio" if job["kind"] == "portfolio" else f"agent-{job['propertyId']}")]
            agent["status"] = "working" if matching else "idle"
            if matching:
                agent["lastAction"] = matching[-1]["message"]
        return agents

    def find(self, kind: str, property_id: str, search: str = "", **filters):
        self.require_property(property_id)
        records = self.store.all(kind, property_id)
        for key, value in filters.items():
            if value and value not in ("all", "All"):
                records = [r for r in records if str(r.get(key, "")).casefold() == value.casefold()]
        if search:
            tokens = search.casefold().split()
            records = [r for r in records if all(token in json.dumps(public(r), ensure_ascii=False).casefold() for token in tokens)]
        return records

    def upload_document(self, property_id: str, filename: str, data: bytes, category: str):
        self.require_property(property_id)
        filename = Path(filename).name[:180]
        if Path(filename).suffix.lower() not in (".pdf", ".txt", ".md", ".json", ".csv"):
            raise ValueError("Upload a PDF, text, Markdown, JSON or CSV document.")
        if not data or len(data) > 25 * 1024 * 1024:
            raise ValueError("Document must be nonempty and at most 25 MB.")
        try:
            text, pages = extract_text(filename, data)
        except Exception as error:
            raise ValueError("The document could not be read. Check that the PDF is valid and not encrypted.") from error
        identifier = uid("doc")
        saved_filename = identifier + Path(filename).suffix.lower()
        (self.store.directory / "files" / saved_filename).write_bytes(data)
        document = dict(id=identifier, title=Path(filename).stem.replace("_", " "), filename=filename,
                        category=category or "Uploaded sources", jurisdiction=self.require_property(property_id).get("operator", "Demonstration site"),
                        pages=pages, size=len(data), uploadedAt=now(), url=f"/api/documents/{identifier}/file",
                        extractedText=text[:500000], _path=saved_filename, _propertyId=property_id)
        self.store.put("document", document, property_id)
        created = 0
        # Explicit import format avoids inventing statutory rules from arbitrary prose.
        # [REQ:CODE] P-101 | Requirement title | Requirement description
        tags = {c["tag"]: c for c in self.store.all("component", property_id)}
        for page, page_text in enumerate(text.split("\f"), 1):
            for match in re.finditer(r"\[REQ:([\w.-]+)\]\s*([\w-]+)\s*\|\s*([^|\n]+)\|\s*([^\n]+)", page_text):
                code, tag, title, description = (part.strip() for part in match.groups())
                component = tags.get(tag)
                if not component:
                    continue
                requirement_id = uid("req")
                self.store.put("requirement", dict(id=requirement_id, code=code, title=title,
                    description=description, system=component["system"], componentId=component["id"], status="pending",
                    sourceId=identifier, sourceTitle=document["title"], sourcePage=page,
                    evidence="Imported project requirement. Supporting evidence has not been assessed.", _check="CUSTOM"), property_id)
                created += 1
        detail = f"Extracted {len(text):,} characters from {pages} page(s); imported {created} explicit project requirement(s)."
        if not text.strip():
            detail += " This appears to be a scan; OCR/model access is needed to read its contents."
        self.store.event(property_id, f"agent-{property_id}", "document.ingested", document["title"], detail)
        self.recompute(property_id)
        return document

    def assess_evidence(self, property_id: str, component: dict, requirement: dict, evidence: dict):
        payload = evidence.get("_assessment")
        if payload is None:
            try:
                payload = json.loads(evidence.get("_text", ""))
            except (json.JSONDecodeError, TypeError):
                return "pending", "Attachment stored. It requires a machine-readable matching record or model-assisted review; filename and note are not proof."
        if not isinstance(payload, dict):
            return "pending", "Evidence JSON must be an object with propertyId, componentId, requirementId and outcome."
        if payload.get("propertyId") != property_id:
            return "issue", "Rejected evidence: propertyId does not match this property."
        if payload.get("componentId") != component["id"] or payload.get("tag", component["tag"]) != component["tag"]:
            return "issue", f"Rejected evidence: equipment identity does not match {component['tag']}."
        if payload.get("requirementId") != requirement["id"]:
            return "issue", "Rejected evidence: requirementId does not match this check."
        if payload.get("outcome") not in ("pass", "fail"):
            return "pending", "The record needs an explicit outcome of pass or fail."
        synthetic = "Synthetic fixture" if payload.get("synthetic") else "Submitted project record"
        if payload["outcome"] == "fail":
            return "issue", f"{synthetic} matches property and asset, and records a failing observation. Physical condition remains as reported by this source."
        return "verified", f"{synthetic} matches property, equipment and requirement and records a pass. This verifies record consistency, not physical condition or legal compliance."

    def upload_evidence(self, property_id: str, component_id: str, requirement_id: str,
                        filename: str, data: bytes, note: str):
        component = self.component(property_id, component_id)
        requirement = self.store.get("requirement", requirement_id, property_id)
        if not requirement or requirement["componentId"] != component_id:
            raise ValueError("Requirement must belong to the selected component and property.")
        filename = Path(filename).name[:180]
        suffix = Path(filename).suffix.lower()
        if suffix not in (".pdf", ".txt", ".md", ".json", ".csv", ".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("Evidence must be PDF, text, JSON or a PNG/JPEG/WebP image.")
        if not data or len(data) > 10 * 1024 * 1024:
            raise ValueError("Evidence must be nonempty and at most 10 MB.")
        text = ""
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                text, _ = extract_text(filename, data)
            except Exception:
                raise ValueError("Evidence could not be parsed. Upload a valid unencrypted file.")
        identifier = uid("ev")
        saved_filename = identifier + suffix
        (self.store.directory / "files" / saved_filename).write_bytes(data)
        evidence = dict(id=identifier, componentId=component_id, requirementId=requirement_id,
            filename=filename, note=note[:4000], status="pending", createdAt=now(),
            url=f"/api/evidence/{identifier}/file", _text=text[:500000], _path=saved_filename, _propertyId=property_id)
        status, reason = self.assess_evidence(property_id, component, requirement, evidence)
        evidence["status"] = status
        self.store.put("evidence", evidence, property_id)
        requirement.update(status=status, evidence=reason)
        self.store.put("requirement", requirement, property_id)
        self.recompute(property_id)
        self.store.event(property_id, f"agent-{property_id}", "evidence.assessed", f"Evidence checked for {component['tag']}", reason, component_id)
        self.save_memory(property_id, f"Evidence {identifier} for {component['tag']} / {requirement['code']}: {reason}", f"evidence:{identifier}")
        return evidence

    def save_memory(self, property_id: str, content: str, source: str, identifier: str | None = None):
        self.require_property(property_id)
        memory = dict(id=identifier or uid("mem"), propertyId=property_id, content=content[:12000], source=source, createdAt=now())
        self.store.put("memory", memory, property_id)
        return memory

    def propose_purchase(self, property_id: str, component_id: str, description: str, amount: float, currency: str):
        self.component(property_id, component_id)
        if not 0 < amount <= 1_000_000 or not description.strip() or len(description) > 2000:
            raise ValueError("Provide a description and an amount greater than zero and at most 1,000,000.")
        if not re.fullmatch(r"[A-Z]{3}", currency.upper()):
            raise ValueError("Currency must be a three-letter ISO code.")
        purchase = dict(id=uid("purchase"), componentId=component_id, description=description.strip(), amount=round(amount, 2),
                        currency=currency.upper(), status="awaiting_authorization", createdAt=now())
        self.store.put("purchase", purchase, property_id)
        self.store.event(property_id, f"agent-{property_id}", "purchase.proposed", "Purchase proposal saved",
                         f"{purchase['currency']} {purchase['amount']:.2f}: {description}. No order placed or payment executed.", component_id)
        return purchase

    def create_job(self, property_id: str, kind="inspection", scope="all", goal=""):
        self.require_property(property_id)
        with self.submit_lock:
            current = [j for j in self.store.all("job", property_id) if j["status"] in ("running", "queued") and j["kind"] == kind]
            if current:
                return current[-1]
            job = dict(id=uid("job"), propertyId=property_id, kind=kind, status="queued", progress=0,
                message="Queued for the local evidence-analysis worker.", result=None, createdAt=now(), updatedAt=now(),
                _scope=scope, _goal=goal, _completedComponents=[])
            self.store.put("job", job, property_id)
            self.store.event(property_id, "portfolio" if kind == "portfolio" else f"agent-{property_id}", "job.queued",
                             "Portfolio mission queued" if kind == "portfolio" else "Inspection queued",
                             goal or f"Scope: {scope}. Checks use persisted project sources and evidence.")
            if self.start_workers:
                self.futures[job["id"]] = self.executor.submit(self.execute_job, job["id"])
            return job

    def recover_jobs(self):
        for agent in self.store.all("agent"):
            agent["status"] = "idle"
            self.store.put("agent", agent)
        for job in self.store.all("job"):
            if job["status"] in ("queued", "running"):
                job.update(status="queued", message="Recovered interrupted job from local checkpoint.", updatedAt=now())
                self.store.put("job", job, job["propertyId"])
                self.store.event(job["propertyId"], "portfolio", "job.recovered", "Work resumed after restart",
                                 f"Checkpoint retained for {len(job.get('_completedComponents', []))} component(s).")
                self.futures[job["id"]] = self.executor.submit(self.execute_job, job["id"])

    def progress(self, job, percentage, message):
        job.update(progress=percentage, message=message, updatedAt=now())
        self.store.put("job", job, job["propertyId"])

    def check_requirement(self, property_id, component, requirement):
        code = requirement.get("_check", "CUSTOM")
        if code == "ID":
            count = sum(c["tag"] == component["tag"] for c in self.store.all("component", property_id))
            return ("verified", "Scene register contains one matching asset tag. This establishes model identity only.") if count == 1 else (
                "issue", "Asset tag is missing or duplicated in the scene register.")
        if code == "LOC":
            x, y, z = component["position"]
            room = room_for(property_id)
            valid = -room["width"] / 2 <= x <= room["width"] / 2 and 0 <= y <= room["height"] and -room["depth"] / 2 <= z <= room["depth"] / 2
            return ("verified", f"Registered origin ({x}, {y}, {z}) is inside the plant-room model bounds.") if valid else (
                "issue", "Registered component origin falls outside the scene bounds.")
        evidence = [e for e in self.store.all("evidence", property_id) if e["requirementId"] == requirement["id"]]
        if evidence:
            # Use the latest submitted record; append-only originals remain in the evidence history.
            return self.assess_evidence(property_id, component, requirement, evidence[-1])
        return "pending", "No matching evidence record is attached. The scene appearance does not establish this requirement."

    def execute_job(self, identifier: str):
        job = self.store.claim_job(identifier)
        if not job:
            return
        property_id = job["propertyId"]
        agent_id = "portfolio" if job["kind"] == "portfolio" else f"agent-{property_id}"
        agent = self.store.get("agent", agent_id)
        if agent:
            agent.update(status="working", lastAction="Reading current project context and source records.")
            self.store.put("agent", agent)
        try:
            if job["kind"] == "portfolio":
                self.execute_portfolio(job)
            else:
                self.execute_inspection(job)
        except Exception as error:
            # Exception messages are intentionally bounded and never include credentials or request bodies.
            job.update(status="failed", message=f"Analysis failed ({type(error).__name__}). The checkpoint is preserved; retry the inspection.", updatedAt=now())
            self.store.put("job", job, property_id)
            self.store.event(property_id, agent_id, "job.failed", "Analysis stopped", job["message"])
        finally:
            if agent:
                agent.update(status="idle", lastAction=job["message"])
                self.store.put("agent", agent)

    def execute_inspection(self, job):
        property_id = job["propertyId"]
        agent_id = f"agent-{property_id}"
        components = self.store.all("component", property_id)
        scope = job.get("_scope", "all")
        if scope and scope.lower() not in ("all", "full", "plant room"):
            narrowed = [c for c in components if scope.casefold() in f"{c['id']} {c['tag']} {c['system']} {c['subsystem']}".casefold()]
            if not narrowed:
                raise ValueError("Unknown inspection scope")
            components = narrowed
        documents = self.store.all("document", property_id)
        self.progress(job, 5, "Reading project source documents and persisted evidence.")
        chars = 0
        for document in documents:
            path = self.store.directory / "files" / document["_path"]
            text, pages = extract_text(document["filename"], path.read_bytes())
            chars += len(text)
            document.update(extractedText=text[:500000], pages=pages)
            self.store.put("document", document, property_id)
        self.store.event(property_id, agent_id, "tool.read_documents", "Project sources indexed",
                         f"Read {len(documents)} document(s), {chars:,} extracted characters. No vision service or statutory certification was used.")
        completed = set(job.get("_completedComponents", []))
        all_requirements = self.store.all("requirement", property_id)
        for index, component in enumerate(components):
            if component["id"] in completed:
                continue
            checks = [r for r in all_requirements if r["componentId"] == component["id"]]
            for requirement in checks:
                status, reason = self.check_requirement(property_id, component, requirement)
                requirement.update(status=status, evidence=reason)
                self.store.put("requirement", requirement, property_id)
            failures = sum(r["status"] == "issue" for r in checks)
            pending = sum(r["status"] in ("pending", "unknown") for r in checks)
            self.store.event(property_id, agent_id, "tool.assess_component", f"Checked {component['tag']}",
                f"{len(checks)} project checks assessed: {sum(r['status'] == 'verified' for r in checks)} verified records, "
                f"{pending} missing/unknown, {failures} conflicting or failing record(s).", component["id"])
            completed.add(component["id"])
            job["_completedComponents"] = sorted(completed)
            self.progress(job, 10 + int((index + 1) / len(components) * 75), f"Checked {index + 1}/{len(components)} components: {component['tag']}.")
        self.recompute(property_id)
        self.progress(job, 90, "Saving source-linked findings, memory and the evidence report.")
        stats = self.stats(property_id)
        summary = (f"Checked {len(components)} components against project specifications. "
                   f"Property totals: {stats['verified']}/{stats['total']} verified records, {stats['pending']} pending, "
                   f"{stats['issue']} issues, {stats['unknown']} unknown. Results concern original demo evidence, not site certification.")
        self.save_memory(property_id, summary, f"job:{job['id']}", f"memory-{job['id']}")
        self.write_report(property_id)
        job.update(status="completed", progress=100, message=summary,
                   result=dict(componentsChecked=len(components), stats=stats, reportUrl=f"/api/properties/{property_id}/report",
                               mode="local_deterministic", modelUsed=False), updatedAt=now())
        self.store.put("job", job, property_id)
        self.store.event(property_id, agent_id, "job.completed", "Inspection complete", summary)
        coordinator = self.store.get("agent", "portfolio")
        coordinator["lastAction"] = f"Reviewed {self.require_property(property_id)['name']}: {stats['issue']} issue(s), {stats['pending']} pending check(s)."
        self.store.put("agent", coordinator)
        if not self.store.get("chat", f"chat-{job['id']}", property_id):
            self.store.put("chat", dict(id=f"chat-{job['id']}", role="assistant", content=summary +
                f" Download the evidence report from /api/properties/{property_id}/report.", createdAt=now(),
                sources=[dict(id=f"{property_id}-spec", title="Mechanical & Electrical Project Requirements", page=1)]), property_id)

    def execute_portfolio(self, job):
        results = []
        for index, prop in enumerate(self.store.all("property")):
            self.progress(job, 5 + index * 30, f"Coordinating {prop['name']}'s scoped property agent.")
            child = self.create_job(prop["id"], "inspection", "all", f"Portfolio mission {job['id']}")
            if child["id"] not in self.futures:
                self.execute_job(child["id"])
            elif not self.futures[child["id"]].done():
                # Workers run child inspections concurrently; this coordinator waits on actual work.
                self.futures[child["id"]].result(timeout=180)
            child = self.store.get("job", child["id"])
            results.append(dict(propertyId=prop["id"], jobId=child["id"], status=child["status"], stats=self.stats(prop["id"])))
            self.store.event(job["propertyId"], "portfolio", "agent.handoff", f"{prop['name']} agent returned findings",
                             f"Job {child['id']}: {child['status']}.")
        failed = any(result["status"] != "completed" for result in results)
        job.update(status="failed" if failed else "completed", progress=100,
                   message="Portfolio checks finished." if not failed else "Portfolio run finished with a failed property job; inspect its event log.",
                   result=dict(properties=results, mode="local_deterministic"), updatedAt=now())
        self.store.put("job", job, job["propertyId"])
        summaries = []
        for result in results:
            stats = result["stats"]
            name = self.require_property(result["propertyId"])["name"]
            summaries.append(f"{name}: {stats['verified']}/{stats['total']} verified project records, "
                             f"{stats['pending']} pending and {stats['issue']} issue(s).")
        self.save_memory(job["propertyId"], job["message"] + " " + " ".join(summaries),
                         f"job:{job['id']}", f"memory-{job['id']}")
        self.store.event(job["propertyId"], "portfolio", "job.completed" if not failed else "job.failed", "Portfolio mission finished", job["message"])

    def report_data(self, property_id: str):
        return public(dict(property=self.require_property(property_id), generatedAt=now(),
            disclosure="Original demonstration project. Synthetic baseline observations. Record consistency checks do not establish physical condition or statutory certification.",
            stats=self.stats(property_id), components=self.store.all("component", property_id),
            requirements=self.store.all("requirement", property_id), documents=self.store.all("document", property_id),
            evidence=self.store.all("evidence", property_id), purchases=self.store.all("purchase", property_id)))

    def write_report(self, property_id: str):
        data = self.report_data(property_id)
        esc = lambda value: html.escape(str(value))
        rows = "".join(f"<tr><td>{esc(r['code'])}</td><td>{esc(r['componentId'])}</td><td>{esc(r['title'])}</td>"
            f"<td class='{esc(r['status'])}'>{esc(r['status'])}</td><td>{esc(r['evidence'])}</td>"
            f"<td>{esc(r['sourceTitle'])}, p. {r['sourcePage']}</td></tr>" for r in data["requirements"])
        content = f"""<!doctype html><html lang='en'><meta charset='utf-8'><title>{esc(data['property']['name'])} Evidence Report</title>
<style>body{{font:14px system-ui;color:#18312b;max-width:1400px;margin:48px auto;padding:0 24px}}h1{{font-size:32px}}p{{line-height:1.6}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;border:1px solid #d8e0dc;text-align:left;vertical-align:top}}th{{background:#edf3f0}}
.issue{{color:#b13232}}.pending{{color:#9c6a15}}.verified{{color:#247354}}.notice{{padding:16px;background:#fff4dd}}</style>
<h1>STEWARD / {esc(data['property']['name'])}</h1><p>Evidence report · {esc(data['generatedAt'])}</p>
<p class='notice'>{esc(data['disclosure'])}</p><p>{esc(json.dumps(data['stats']))}</p>
<table><thead><tr><th>Check</th><th>Component</th><th>Requirement</th><th>Status</th><th>Evidence assessment</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></html>"""
        path = self.store.directory / "files" / f"{property_id}-report.html"
        path.write_text(content)
        return path

    def chat(self, property_id: str, message: str):
        self.require_property(property_id)
        user = dict(id=uid("chat"), role="user", content=message, createdAt=now())
        self.store.put("chat", user, property_id)
        lower = message.casefold()
        job = None
        sources = []
        components = self.store.all("component", property_id)
        matched = [c for c in components if c["tag"].casefold() in lower or c["id"].casefold() in lower]
        requirements = self.store.all("requirement", property_id)
        if any(term in lower for term in ("inspect", "analyse", "analyze", "run inspection", "start survey", "scan")):
            portfolio = any(term in lower for term in ("all properties", "all sites", "portfolio", "both sites", "three properties"))
            scope = matched[0]["id"] if matched and not portfolio else "all"
            job = self.create_job(property_id, "portfolio" if portfolio else "inspection", scope, message)
            answer = f"I've queued {'every site agent' if portfolio else 'the property inspection worker'} ({job['id']}). " \
                     "It will read the source files, check asset identities and locations, validate attached records, and persist findings and a report. " \
                     "These are local evidence checks; no model vision or physical inspection is being simulated."
        elif lower.startswith("remember ") or lower.startswith("remember:"):
            content = message[9:].strip() if lower.startswith("remember:") else message[9:].strip()
            memory = self.save_memory(property_id, content, f"chat:{user['id']}")
            answer = "Saved this to the property's persistent local memory: " + memory["content"]
        elif any(term in lower for term in ("memory", "remember", "history")):
            memories = self.store.all("memory", property_id)[-5:]
            answer = "Recent source-linked property memory:\n\n" + "\n\n".join(f"• {m['content']} (source: {m['source']})" for m in memories)
        elif any(term in lower for term in ("all properties", "portfolio", "three properties")):
            answer = "Current portfolio records:\n" + "\n".join(
                f"• {p['name']}: {p['readiness']}% project evidence complete; {p['openIssues']} issue(s)." for p in self.store.all("property"))
        elif any(term in lower for term in ("report", "export", "handover")):
            self.write_report(property_id)
            answer = f"The current source-linked evidence report is ready: /api/properties/{property_id}/report. " \
                     "It includes every project check and its evidence assessment, with the synthetic-data disclosure."
        elif matched:
            selected = matched[:3]
            sections = []
            for component in selected:
                checks = [r for r in requirements if r["componentId"] == component["id"]]
                sections.append(f"{component['tag']} — {component['name']} ({component['status']})\n" +
                    "\n".join(f"• {r['title']}: {r['status']}. {r['evidence']}" for r in checks))
                sources.extend(dict(id=r["sourceId"], title=r["sourceTitle"], page=r["sourcePage"]) for r in checks)
            answer = "\n\n".join(sections)
        elif any(term in lower for term in ("buy", "purchase", "order", "payment")):
            answer = "I can save an equipment-linked purchase proposal from the component panel. Provide the item, price and asset. " \
                     "Proposals remain awaiting authorization. This local application does not place orders or charge cards."
        else:
            stats = self.stats(property_id)
            open_checks = [r for r in requirements if r["status"] in ("issue", "pending")]
            terms = set(re.findall(r"[a-z0-9]+", lower)) - {"what", "the", "is", "are", "a", "and", "of", "for", "to", "show", "me"}
            ranked = sorted(open_checks or requirements, key=lambda r: len(terms & set(re.findall(r"[a-z0-9]+", json.dumps(public(r)).casefold()))), reverse=True)[:4]
            answer = f"{self.require_property(property_id)['name']} has {stats['verified']}/{stats['total']} verified project records, " \
                     f"{stats['pending']} pending checks and {stats['issue']} issue(s).\n\n" + "\n".join(
                         f"• {r['code']} / {r['componentId']}: {r['title']} — {r['evidence']}" for r in ranked)
            answer += "\n\nAsk about an asset tag such as P-101, say ‘inspect this property’, ‘inspect all properties’, ‘show memory’, or ‘export report’."
            sources = [dict(id=r["sourceId"], title=r["sourceTitle"], page=r["sourcePage"]) for r in ranked]
        if not job and self.model.configured:
            try:
                context = public(dict(property=self.require_property(property_id), stats=self.stats(property_id),
                    components=matched or components[:8], requirements=[r for r in requirements if not matched or r["componentId"] in {c['id'] for c in matched}][:32],
                    memories=self.store.all("memory", property_id)[-8:], localAnswer=answer))
                synthesis = self.model.synthesize(message, context)
                if synthesis:
                    answer = synthesis
                    self.store.event(property_id, f"agent-{property_id}", "model.completed", "Model synthesis completed",
                                     f"Grounded response generated by configured {self.model.provider} adapter. No external actions performed.")
            except Exception as error:
                answer = "The configured model request failed; here is the local evidence-based answer.\n\n" + answer
                self.store.event(property_id, f"agent-{property_id}", "model.failed", "Model request failed",
                                 f"{type(error).__name__}: check provider access and configuration locally. Credentials and request details are omitted.")
        unique_sources = list({(s["id"], s.get("page")): s for s in sources}.values())
        assistant = dict(id=uid("chat"), role="assistant", content=answer, createdAt=now(), sources=unique_sources)
        self.store.put("chat", assistant, property_id)
        self.store.event(property_id, f"agent-{property_id}", "chat.responded", "Property agent responded",
                         "Used local project records and source-linked context." + (" Model adapter requested." if self.model.configured else " No model provider configured."))
        return dict(message=assistant, **({"job": job} if job else {}))
