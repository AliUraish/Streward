"""Regulations (contract 4 §5): real government sources cached locally with attribution, explained in our words.

The REGULATIONS stream downloads the official PDFs into `backend/data/regulations/` and writes
`backend/seed/regulations/regulations.json`; this module only reads them (never writes there). A record is
`{id, jurisdiction: ENG-UK | VIC-AU, instrument, provision, title, officialUrl, pdfPath, licence, retrievedAt, summary,
appliesTo}`; `summary` is our wording, never a long quotation. Sites map to jurisdictions (`bristol-pumps` → England,
`myer-plant` → Victoria). Obligations carry citation hints `{jurisdiction, instrument, provision, keywords}` that are
resolved to regulation ids at read time, so they keep working whatever ids the source file uses; compliance issues
cite their obligation's regulations, or a per-kind hint. This is a demo rule pack, not legal advice.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .env import env
from .errors import RealityError

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DEFAULT_FILE = BACKEND / "seed" / "regulations" / "regulations.json"
SITE_JURISDICTION = {"myer-plant": "VIC-AU", "bristol-pumps": "ENG-UK"}
DISCLAIMER = "Demo rule pack: our own plain-language summaries with links to the official text. Not legal advice."
OHS = "Occupational Health and Safety Regulations 2017"
BLD = "Building Regulations 2018"
PSSR = "Pressure Systems Safety Regulations 2000"
WHSW = "Workplace (Health, Safety and Welfare) Regulations 1992"
HSWA = "Health and Safety at Work etc. Act 1974"
KIND_HINTS = {
    "overpressure": {"VIC-AU": [dict(instrument=OHS, provision="Part 5.1", keywords=["pressure equipment", "plant"])],
                     "ENG-UK": [dict(instrument=PSSR, provision="regulation 7", keywords=["safe operating limits"])]},
    "sump_overflow": {"ENG-UK": [dict(instrument=WHSW, provision="regulation 12", keywords=["floors", "traffic routes"])],
                      "VIC-AU": [dict(instrument=OHS, provision="Part 5.1", keywords=["plant"])]},
    "walkway_closure": {"ENG-UK": [dict(instrument=WHSW, provision="regulation 12", keywords=["floors", "traffic routes"])]},
    "certificate_expired": {"ENG-UK": [dict(instrument=PSSR, provision="regulation 9", keywords=["examination"])],
                            "VIC-AU": [dict(instrument=OHS, provision="Part 5.1", keywords=["pressure equipment"])]},
    "inspection_overdue": {"VIC-AU": [dict(instrument=BLD, provision="Part 15", keywords=["essential safety measures", "fire extinguishers"])],
                           "ENG-UK": [dict(instrument=HSWA, provision="section 2", keywords=["general duties"])]},
    "valve_not_fixed": {"VIC-AU": [dict(instrument=OHS, provision="Part 5.1", keywords=["plant", "maintenance"])],
                        "ENG-UK": [dict(instrument=PSSR, provision="regulation 12", keywords=["maintenance"])]},
    "valve_uncertain": {"VIC-AU": [dict(instrument=OHS, provision="Part 5.1", keywords=["plant"])],
                        "ENG-UK": [dict(instrument=PSSR, provision="regulation 12", keywords=["maintenance"])]},
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").casefold()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 2 or t.isdigit()}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


class RegulationService:
    def __init__(self, service):
        self.service = service
        self._cache: tuple[float, list[dict]] | None = None

    @property
    def path(self) -> Path:
        return Path(env("STEWARD_REGULATIONS_FILE", "") or DEFAULT_FILE)

    def records(self) -> list[dict]:
        path = self.path
        if not path.is_file():
            return []
        mtime = path.stat().st_mtime
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        try:
            payload = json.loads(path.read_text())
        except (ValueError, OSError):
            return []
        items = payload.get("records") if isinstance(payload, dict) else payload
        records = [r for r in (items or []) if isinstance(r, dict) and r.get("id") and r.get("jurisdiction")]
        self._cache = (mtime, records)
        return records

    def pdf_file(self, record: dict) -> Path | None:
        raw = str(record.get("pdfPath") or "")
        if not raw:
            return None
        candidate = Path(raw)
        options = [candidate] if candidate.is_absolute() else [ROOT / candidate, BACKEND / candidate, self.path.parent / candidate,
                                                              BACKEND / "data" / "regulations" / candidate.name]
        allowed = [(BACKEND / "data" / "regulations").resolve(), (BACKEND / "seed" / "regulations").resolve(), self.path.parent.resolve()]
        for option in options:
            try:
                resolved = option.resolve()
            except OSError:
                continue
            if resolved.is_file() and resolved.suffix.lower() == ".pdf" and any(str(resolved).startswith(str(root)) for root in allowed):
                return resolved
        return None

    def view(self, record: dict) -> dict:
        return dict(id=record["id"], jurisdiction=record["jurisdiction"], instrument=record.get("instrument"), provision=record.get("provision"),
                    title=record.get("title"), officialUrl=record.get("officialUrl"), licence=record.get("licence"), retrievedAt=record.get("retrievedAt"),
                    summary=record.get("summary"), appliesTo=record.get("appliesTo"), fileUrl=f"/api/regulations/{record['id']}/file",
                    cached=self.pdf_file(record) is not None, disclaimer=DISCLAIMER)

    def list(self, site_id: str | None = None) -> list[dict]:
        records = self.records()
        if site_id:
            self.service.require_property(site_id)
            jurisdiction = SITE_JURISDICTION.get(site_id)
            records = [r for r in records if r["jurisdiction"] == jurisdiction or site_id in self._applies_sites(r)]
        return [self.view(r) for r in records]

    @staticmethod
    def _applies_sites(record: dict) -> set[str]:
        applies = record.get("appliesTo")
        if isinstance(applies, dict):
            return set(applies.get("siteIds") or applies.get("sites") or [])
        if isinstance(applies, list):
            return {a for a in applies if isinstance(a, str) and a in SITE_JURISDICTION}
        return set()

    def get(self, regulation_id: str) -> dict:
        record = next((r for r in self.records() if r["id"] == regulation_id), None)
        if not record:
            raise RealityError("Regulation not found.", "NOT_FOUND", "List regulations with GET /api/regulations?siteId=.", 404)
        return record

    def attribution(self, record: dict) -> str:
        text = f"Source: {record.get('instrument') or record.get('title')} ({record.get('officialUrl') or 'official source'}). " \
               f"Licence: {record.get('licence') or 'see source'}. Retrieved {record.get('retrievedAt') or 'unknown'}."
        return text.encode("latin-1", "replace").decode("latin-1")[:900]

    # ---- citations -------------------------------------------------------------------------------------

    def resolve(self, hint: dict, jurisdiction: str | None = None) -> list[str]:
        """Best-matching regulation ids for one citation hint (instrument + provision + keywords)."""
        jurisdiction = hint.get("jurisdiction") or jurisdiction
        candidates = [r for r in self.records() if not jurisdiction or r["jurisdiction"] == jurisdiction]
        instrument = _tokens(hint.get("instrument", "")) - {"the", "and", "etc"}
        numbers = _numbers(hint.get("provision", ""))
        keywords = [k.casefold() for k in hint.get("keywords", [])]
        scored = []
        for record in candidates:
            haystack_instrument = _tokens(f"{record.get('instrument', '')} {record.get('title', '')}")
            if instrument and len(instrument & haystack_instrument) < max(2, len(instrument) // 2):
                continue
            score = 3
            provision_numbers = _numbers(record.get("provision", ""))
            if numbers and numbers & provision_numbers:
                score += 4
            text = _norm(" ".join(str(record.get(k, "")) for k in ("title", "provision", "summary")))
            score += sum(1 for k in keywords if _norm(k) in text)
            scored.append((score, record["id"]))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not scored:
            return []
        best = scored[0][0]
        return [rid for score, rid in scored if score == best][:2]

    def resolve_many(self, hints: list[dict] | None, jurisdiction: str | None = None) -> list[str]:
        ids: list[str] = []
        for hint in hints or []:
            for rid in self.resolve(hint, jurisdiction):
                if rid not in ids:
                    ids.append(rid)
        return ids

    def for_obligation(self, obligation: dict) -> list[str]:
        return self.resolve_many(obligation.get("cites"), SITE_JURISDICTION.get(obligation.get("siteId")))

    def for_issue(self, issue: dict) -> list[str]:
        site = issue.get("siteId")
        jurisdiction = SITE_JURISDICTION.get(site)
        ids: list[str] = []
        if issue.get("obligationId"):
            obligation = self.service.store.get("obligation", issue["obligationId"], site)
            if obligation:
                ids = self.for_obligation(obligation)
        if not ids:
            hints = (KIND_HINTS.get(issue.get("kind") or "", {}) or {}).get(jurisdiction, [])
            ids = self.resolve_many([dict(h, jurisdiction=jurisdiction) for h in hints], jurisdiction)
        return ids

    def why(self, regulation_ids: list[str]) -> list[dict]:
        records = {r["id"]: r for r in self.records()}
        out = []
        for rid in regulation_ids:
            record = records.get(rid)
            if record:
                out.append(dict(regulationId=rid, instrument=record.get("instrument"), provision=record.get("provision"), title=record.get("title"),
                                summary=record.get("summary"), officialUrl=record.get("officialUrl"), fileUrl=f"/api/regulations/{rid}/file",
                                licence=record.get("licence")))
        return out

    def reason_text(self, regulation_ids: list[str], fallback: str) -> str:
        why = self.why(regulation_ids)
        if not why:
            return fallback
        first = why[0]
        summary = (first.get("summary") or "").strip()
        return f"{first.get('instrument')}, {first.get('provision')}: {summary[:260]}".strip()
