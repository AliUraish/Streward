"""Valve inspection ingest (contract 3 §3 step 4).

`vision/` is a separate package; the backend never imports it. It only reads its results file
(`vision/results/<site>.json`) or an equivalent JSON body and turns each valve result into a `finding` record and,
for `not_fixed` / `uncertain`, an issue. Accepted shapes: a list of results, or an object with `results` or
`valves` (plus optional `model`, `generatedAt`, `runId`). Each result: `{assetTag, status: fixed | not_fixed |
uncertain, score, threshold, model, frames: [...], explanation?: {finding, evidence, confidence,
recommendedAction}, synthetic?, defect?, mode?: baseline | peer, pinWarning?, reason?, anomalyPeak?, anomalyGrid?}`.
The score is an embedding anomaly score, not a trained defect classifier; findings say which comparison was used
(`baseline`: the valve's own accepted-good capture; `peer`: the site's other valves) and carry any `pinWarning`.
A valve whose pin is still estimated is never presented as a located defect: the finding says `located: false` and
the issue text says the location is unconfirmed. Only the site's engineer, manager, the director or the owner's
agent may ingest for a site. Re-ingesting the same file updates the same records.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .agents import authorize
from .errors import RealityError
from .store import now, uid

ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("fixed", "not_fixed", "uncertain")
SCORE_NOTE = "Embedding anomaly score, not a trained defect classifier; it does not certify equipment or replace an engineer's sign-off."
MODE_PHRASE = {"baseline": "compared with this valve's own clean baseline", "peer": "compared with the site's other valves"}
NOT_SYNTHETIC = (None, "", "none")


def is_synthetic(result: dict) -> bool:
    defect = result.get("defect")
    labelled = isinstance(defect, str) and defect.strip().lower() not in NOT_SYNTHETIC
    return result.get("synthetic") is True or labelled


def score_note(mode: str | None) -> str:
    phrase = MODE_PHRASE.get(mode or "")
    return f"{SCORE_NOTE} Score {phrase}." if phrase else SCORE_NOTE


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
            meta = {k: payload.get(k) for k in ("model", "generatedAt", "runId", "siteId", "mode", "pinWarning", "scoreDefinition", "honesty", "inspectedBy",
                                                "frameSource") if payload.get(k) is not None}
            if isinstance(meta.get("model"), dict):
                meta["model"] = meta["model"].get("id") or json.dumps(meta["model"])[:120]
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
        actor = authorize(actor, "ingest_vision", site_id)
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
            synthetic = is_synthetic(result)
            mode = result.get("mode") or meta.get("mode")
            pin_warning = result.get("pinWarning") or meta.get("pinWarning")
            pin_source = component.get("pinSource") or result.get("pinSource") or "estimated"
            located = pin_source == "placed"
            grid = result.get("anomalyGrid") if isinstance(result.get("anomalyGrid"), list) and len(result.get("anomalyGrid")) <= 32 else None
            finding = dict(id=f"fnd-{site_id}-{component['tag']}", siteId=site_id, assetTag=component["tag"], componentId=component["id"], status=status,
                           score=score, threshold=threshold, uncertainAbove=result.get("uncertainAbove"), model=result.get("model") or meta.get("model"),
                           frames=frames, explanation=explanation, reason=(str(result["reason"])[:400] if result.get("reason") else None),
                           defect=result.get("defect") if result.get("defect") not in NOT_SYNTHETIC else None, mode=mode, pinWarning=pin_warning,
                           pinSource=pin_source, located=located, anomalyPeak=result.get("anomalyPeak") if isinstance(result.get("anomalyPeak"), dict) else None,
                           anomalyGrid=grid, baseline=result.get("baseline") if isinstance(result.get("baseline"), (dict, str)) else None,
                           frameSource=result.get("frameSource") or meta.get("frameSource"), inspectedBy=result.get("inspectedBy") or meta.get("inspectedBy") or actor,
                           source="vision", synthetic=synthetic, runId=run_id, ingestedAt=now(), scoreNote=score_note(mode), issueId=None)
            issue_id = f"iss-vision-{site_id[:2]}-{component['tag'].lower()}"
            if status in ("not_fixed", "uncertain"):
                severity = "high" if status == "not_fixed" else "medium"
                detail = (explanation or {}).get("finding") or f"anomaly score {score} vs threshold {threshold}"
                phrase = MODE_PHRASE.get(mode or "")
                text = (("Location unconfirmed (estimated pin): " if not located else "")
                        + f"Valve inspection{f' ({phrase})' if phrase else ''}: {component['tag']} {status.replace('_', ' ')} ({detail})"
                        + (f". Pin warning: {pin_warning}" if pin_warning else ""))
                issue = self.service.issues.raise_issue(
                    site_id, "valve_not_fixed" if status == "not_fixed" else "valve_uncertain", severity, text[:400], asset_tag=component["tag"], issue_id=issue_id,
                    source="vision", run_id=run_id, ref_id=finding["id"], synthetic=synthetic, actor=actor,
                    extra=dict(located=located, pinSource=pin_source, mode=mode, pinWarning=pin_warning))
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
        return dict(siteId=site_id, runId=run_id, ingested=len(findings), issuesRaised=raised, issuesResolved=resolved, findings=findings,
                    mode=meta.get("mode"), pinWarning=meta.get("pinWarning"), scoreNote=score_note(meta.get("mode")), honesty=meta.get("honesty"),
                    unlocated=sum(1 for f in findings if not f["located"]))

    def list(self, site_id: str) -> dict:
        self.service.require_property(site_id)
        findings = sorted(self.store.all("finding", site_id), key=lambda f: f["assetTag"])
        counts = {status: sum(1 for f in findings if f["status"] == status) for status in STATUSES}
        modes = sorted({f.get("mode") for f in findings if f.get("mode")})
        return dict(siteId=site_id, findings=findings, counts=counts, scoreNote=score_note(modes[0] if len(modes) == 1 else None), modes=modes,
                    unlocated=sum(1 for f in findings if not f.get("located")),
                    lastRunId=max(findings, key=lambda f: f["ingestedAt"])["runId"] if findings else None)
