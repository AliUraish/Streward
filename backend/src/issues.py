"""Stored issues (contract 3 §5): raised by scenarios, the vision ingest and agents, merged with computed issues.

Computed issues come from the reality layer (`RealityService.issues`: open work items needing attention, latest
facts outside spec, rejected verdicts, assets without identity). Stored issues are records of kind `issue`:
`{id, siteId, assetTag, componentId, kind, severity, status: open|resolved, summary, refId, pin, at, updatedAt,
scenarioId?, runId?, source: scenario|vision|agent, ownerId?, assigneeId?, obligationId?, documentId?, synthetic,
history}`. Every create, update, assignment and resolution emits a Change of type `issue` (wait event
`issue.changed`). A computed `out_of_range` issue is hidden when a stored open issue already covers the same asset.
"""
from __future__ import annotations

from .errors import RealityError
from .store import now

SEVERITIES = ("low", "medium", "high")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class IssueService:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    @property
    def reality(self):
        return self.service.reality

    def _component(self, site_id: str, asset_tag: str | None) -> dict | None:
        if not asset_tag:
            return None
        return next((c for c in self.store.all("component", site_id) if c["tag"] == asset_tag), None)

    def _save(self, issue: dict, summary: str, actor: str = "director") -> dict:
        issue["updatedAt"] = now()
        self.store.put("issue", issue, issue["siteId"])
        self.reality.mirror.put("issue", issue, issue["siteId"])
        self.reality.emit_change(issue["siteId"], "issue", issue["id"], summary, issue.get("assetTag"),
                                 extra=dict(issueId=issue["id"], kind=issue["kind"], status=issue["status"], severity=issue["severity"],
                                            scenarioId=issue.get("scenarioId"), runId=issue.get("runId"), actor=actor))
        return issue

    def raise_issue(self, site_id: str, kind: str, severity: str, summary: str, asset_tag: str | None = None, issue_id: str | None = None,
                    source: str = "agent", scenario_id: str | None = None, run_id: str | None = None, ref_id: str | None = None,
                    obligation_id: str | None = None, document_id: str | None = None, synthetic: bool = True, actor: str = "director",
                    extra: dict | None = None) -> dict:
        """Create or update (same id) an open issue; the owner comes from the crew ownership table."""
        self.service.require_property(site_id)
        if severity not in SEVERITIES:
            raise RealityError("severity must be low, medium or high.", "INVALID_REQUEST", "Use low, medium or high.")
        component = self._component(site_id, asset_tag)
        if asset_tag and not component:
            raise RealityError(f"Asset {asset_tag} is not registered at {site_id}.", "UNKNOWN_ASSET", "Use a registered asset tag.", 404)
        identifier = issue_id or f"iss-{site_id[:2]}-{kind}-{(asset_tag or 'site').lower()}"
        existing = self.store.get("issue", identifier, site_id)
        owner = self.service.people.responsible_crew(site_id, kind)
        moment = now()
        issue = existing or dict(id=identifier, siteId=site_id, kind=kind, at=moment, history=[], status="open")
        issue.update(assetTag=component["tag"] if component else None, componentId=component["id"] if component else None, severity=severity,
                     summary=summary[:400], refId=ref_id or issue.get("refId") or identifier, pin=(component or {}).get("pin"), status="open",
                     source=source, scenarioId=scenario_id or issue.get("scenarioId"), runId=run_id or issue.get("runId"),
                     ownerId=(owner or {}).get("id") or issue.get("ownerId"), obligationId=obligation_id or issue.get("obligationId"),
                     documentId=document_id or issue.get("documentId"), synthetic=bool(synthetic))
        issue.setdefault("assigneeId", None)
        for key, value in (extra or {}).items():
            if key not in issue or value is not None:
                issue[key] = value
        issue["history"] = (issue.get("history") or [])[-19:] + [dict(at=moment, severity=severity, summary=summary[:300], by=actor)]
        verb = "updated" if existing else "raised"
        return self._save(issue, f"Issue {verb} ({severity}) {kind}" + (f" on {issue['assetTag']}" if issue.get("assetTag") else "") + f": {summary[:300]}", actor)

    def resolve_issue(self, issue_id: str, summary: str, actor: str = "director") -> dict:
        issue = self.stored(issue_id)
        issue["status"] = "resolved"
        issue["resolvedAt"] = now()
        issue["history"] = (issue.get("history") or [])[-19:] + [dict(at=now(), severity=issue["severity"], summary=f"resolved: {summary[:280]}", by=actor)]
        return self._save(issue, f"Issue resolved {issue['kind']}" + (f" on {issue['assetTag']}" if issue.get("assetTag") else "") + f": {summary[:300]}", actor)

    def assign(self, issue_id: str, crew_member_id: str, actor: str) -> dict:
        issue = self.stored(issue_id)
        crew = self.store.get("crew_member", crew_member_id, issue["siteId"])
        if not crew:
            raise RealityError(f"Crew member {crew_member_id} is not on the {issue['siteId']} crew.", "NOT_FOUND",
                               f"List the crew with GET /api/properties/{issue['siteId']}/crew.", 404)
        issue["assigneeId"] = crew_member_id
        issue["history"] = (issue.get("history") or [])[-19:] + [dict(at=now(), severity=issue["severity"], summary=f"assigned to {crew['name']}", by=actor)]
        return self._save(issue, f"Issue {issue['kind']} assigned to {crew['name']} ({crew['role']}) by {actor}.", actor)

    def stored(self, issue_id: str) -> dict:
        issue = self.store.get("issue", issue_id)
        if not issue:
            raise RealityError("Issue not found or not assignable (computed issues follow their work item or fact).", "NOT_FOUND",
                               "List issues with GET /api/properties/{siteId}/issues.", 404)
        return issue

    def list(self, site_id: str, status: str = "open") -> list[dict]:
        """Computed issues (always open) plus stored issues, newest severity first."""
        self.service.require_property(site_id)
        if status not in ("open", "resolved", "all"):
            raise RealityError("status must be open, resolved or all.", "INVALID_REQUEST", "Pass ?status=open|resolved|all.")
        stored = [i for i in self.store.all("issue", site_id) if status == "all" or i["status"] == status]
        covered = {i["assetTag"] for i in stored if i["status"] == "open" and i.get("assetTag")}
        computed = [] if status == "resolved" else [
            {**i, "siteId": site_id, "status": "open", "source": "computed"} for i in self.reality.issues(site_id)
            if not (i["kind"] == "out_of_range" and i["assetTag"] in covered)]
        merged = computed + stored
        merged.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), "" if i.get("status") == "open" else "z", i["at"]))
        return merged

    def get(self, issue_id: str) -> dict:
        issue = self.store.get("issue", issue_id)
        if issue:
            return issue
        for prop in self.store.all("property"):
            for computed in self.reality.issues(prop["id"]):
                if computed["id"] == issue_id:
                    return {**computed, "siteId": prop["id"], "status": "open", "source": "computed"}
        raise RealityError("Issue not found.", "NOT_FOUND", "List issues with GET /api/properties/{siteId}/issues.", 404)

    def open_by_asset(self, site_id: str) -> dict[str, list[dict]]:
        by_asset: dict[str, list[dict]] = {}
        for issue in self.list(site_id, "open"):
            if issue.get("assetTag"):
                by_asset.setdefault(issue["assetTag"], []).append(issue)
        return by_asset
