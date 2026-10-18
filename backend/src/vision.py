"""Valve inspection ingest (contract 3 §3 step 4).

`vision/` is a separate package; the backend never imports it. It only reads its results file
(`vision/results/<site>.json`) or an equivalent JSON body and turns each valve result into a `finding` record and,
for `not_fixed` / `uncertain`, an issue. Accepted shapes: a list of results, or an object with `results` or
`valves` (plus optional `model`, `generatedAt`, `runId`). Each result: `{assetTag, status: fixed | not_fixed |
uncertain, score, threshold, model, frames: [...], explanation?: {finding, evidence, confidence,
recommendedAction}, synthetic?, defect?}`. The score is an embedding anomaly score, not a trained defect classifier;
findings say so. Re-ingesting the same file updates the same records.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .errors import RealityError
from .store import now, uid

ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("fixed", "not_fixed", "uncertain")
SCORE_NOTE = "Embedding anomaly score (cosine distance to the site's valve median), not a trained defect classifier."


class VisionIngest:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.results_root = ROOT / "vision" / "results"

    def load(self, site_id: str, payload) -> tuple[list[dict], dict]:
        if payload in (None, {}, []):
            path = self.results_root / f"{site_id}.json"
            if not path.is_file():
                raise RealityError(f"No vision results at vision/results/{site_id}.json.", "NOT_FOUND",
                                   "Run the vision pipeline, or POST the results JSON as the body.", 404)
            payload = json.loads(path.read_text())
        meta = {}
        if isinstance(payload, dict):
            meta = {k: payload.get(k) for k in ("model", "generatedAt", "runId", "siteId") if payload.get(k) is not None}
            if meta.get("siteId") and meta["siteId"] != site_id:
                raise RealityError("Results file belongs to another site.", "SCOPE", f"POST it to /api/properties/{meta['siteId']}/inspections/vision.", 409)
            results = payload.get("results") or payload.get("valves") or []
        elif isinstance(payload, list):
            results = payload
        else:
            raise RealityError("Results must be a list or an object with results/valves.", "INVALID_REQUEST", "See vision/README for the shape.")
        if not isinstance(results, list) or not results:
            raise RealityError("No valve results to ingest.", "INVALID_REQUEST", "Each result needs assetTag and status.")
        return results, meta

    def ingest(self, site_id: str, payload=None, actor: str = "operator") -> dict:
        self.service.require_property(site_id)
        results, meta = self.load(site_id, payload)
        run_id = str(meta.get("runId") or uid("vrun"))
        findings, raised, resolved = [], 0, 0
        for result in results:
            if not isinstance(result, dict):
                raise RealityError("Each result must be an object.", "INVALID_REQUEST", "See the documented shape.")
            status = result.get("status")
            if status not in STATUSES:
                raise RealityError(f"status must be fixed, not_fixed or uncertain (got {str(status)[:20]}).", "INVALID_REQUEST", "Fix the results file.")
            component = self.service.reality.component_by_tag(site_id, str(result.get("assetTag") or ""))
            score = result.get("score")
            threshold = result.get("threshold")
            for name, value in (("score", score), ("threshold", threshold)):
                if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise RealityError(f"{name} must be a finite number.", "INVALID_REQUEST", "Fix the results file.")
            explanation = result.get("explanation") if isinstance(result.get("explanation"), dict) else None
            frames = [str(f)[:300] for f in (result.get("frames") or [])][:32]
            synthetic = bool(result.get("synthetic") or result.get("defect"))
            finding = dict(id=f"fnd-{site_id}-{component['tag']}", siteId=site_id, assetTag=component["tag"], componentId=component["id"], status=status,
                           score=score, threshold=threshold, model=result.get("model") or meta.get("model"), frames=frames,
                           explanation=explanation, defect=result.get("defect"), source="vision", synthetic=synthetic, runId=run_id,
                           ingestedAt=now(), scoreNote=SCORE_NOTE, issueId=None)
            issue_id = f"iss-vision-{site_id[:2]}-{component['tag'].lower()}"
            if status in ("not_fixed", "uncertain"):
                severity = "high" if status == "not_fixed" else "medium"
                detail = (explanation or {}).get("finding") or f"anomaly score {score} vs threshold {threshold}"
                issue = self.service.issues.raise_issue(
                    site_id, "valve_not_fixed" if status == "not_fixed" else "valve_uncertain", severity,
                    f"Valve inspection: {component['tag']} {status.replace('_', ' ')} ({detail})"[:400], asset_tag=component["tag"], issue_id=issue_id,
                    source="vision", run_id=run_id, ref_id=finding["id"], synthetic=synthetic, actor=actor)
                finding["issueId"] = issue["id"]
                raised += 1
            elif self.store.get("issue", issue_id, site_id) and self.store.get("issue", issue_id, site_id)["status"] == "open":
                self.service.issues.resolve_issue(issue_id, f"Valve inspection run {run_id} reads {component['tag']} as fixed.", actor)
                resolved += 1
            self.store.put("finding", finding, site_id)
            self.service.reality.mirror.put("finding", finding, site_id)
            findings.append(finding)
        self.service.reality.emit_change(site_id, "finding", run_id, f"Valve inspection ingested: {len(findings)} valve(s), {raised} issue(s) raised, "
                                         f"{resolved} resolved.", extra=dict(runId=run_id, findings=len(findings)))
        return dict(siteId=site_id, runId=run_id, ingested=len(findings), issuesRaised=raised, issuesResolved=resolved, findings=findings, scoreNote=SCORE_NOTE)

    def list(self, site_id: str) -> dict:
        self.service.require_property(site_id)
        findings = sorted(self.store.all("finding", site_id), key=lambda f: f["assetTag"])
        counts = {status: sum(1 for f in findings if f["status"] == status) for status in STATUSES}
        return dict(siteId=site_id, findings=findings, counts=counts, scoreNote=SCORE_NOTE,
                    lastRunId=max(findings, key=lambda f: f["ingestedAt"])["runId"] if findings else None)
