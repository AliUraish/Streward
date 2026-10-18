"""Supabase Storage for eye frames and evidence: private buckets, signed URLs (15 minutes), budget-guarded uploads.

The backend uploads what it already stores locally: eye frames (`eye-frames/<site>/<frameId>.jpg`) plus a 320 px
thumbnail made with Pillow (`eye-frames/<site>/thumbs/<frameId>.jpg`), and evidence files named by their SHA-256
(`evidence/<site>/<digest><ext>`). Every upload asks the budget guard first (per-object cap and storage cap). Past 80 %
of the storage cap the oldest eye frames this backend uploaded are deleted from the bucket until usage is back under
70 %; the local copies are always kept. On Pro (SUPABASE_PLAN=pro) the thumbnail URL is a signed image transformation
while the month's origin-image counter is under its cap, then the Pillow thumbnail again. Every signed URL handed to a
browser is charged to the egress estimate; when that budget is spent the caller serves the local file instead.
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

from .store import now

SIGNED_SECONDS = 900
SIGN_CACHE_SECONDS = 600
THUMB_WIDTH = 320
EVIDENCE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic",
                  ".pdf": "application/pdf", ".txt": "text/plain", ".json": "application/json"}
RETENTION_HIGH = 0.8
RETENTION_LOW = 0.7


def thumbnail(data: bytes, width: int = THUMB_WIDTH) -> bytes | None:
    """A JPEG at most `width` px wide (Pillow; Storage image transformations are Pro only)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            if image.width > width:
                height = max(1, round(image.height * width / image.width))
                image = image.resize((width, height), Image.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=72, optimize=True)
            return out.getvalue()
    except Exception:
        return None


class ObjectStore:
    def __init__(self, supa, budget, store, on_event=None, clock=time.time):
        self.supa = supa
        self.budget = budget
        self.store = store
        self.on_event = on_event or (lambda title, detail: None)
        self.clock = clock
        self.lock = threading.Lock()
        self.signed: dict[tuple, tuple[float, str]] = {}
        self.uploads = 0
        self.failures = 0
        self.deleted = 0
        with self.store.lock, self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS supa_objects (
                    bucket TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, kind TEXT NOT NULL, ref_id TEXT NOT NULL,
                    site_id TEXT, uploaded_at TEXT NOT NULL, deleted_at TEXT, PRIMARY KEY (bucket, path));
                CREATE INDEX IF NOT EXISTS supa_objects_ref ON supa_objects(kind, ref_id);
                CREATE INDEX IF NOT EXISTS supa_objects_age ON supa_objects(kind, deleted_at, uploaded_at);
            """)

    # ---- index ------------------------------------------------------------------------------------------------

    def _record(self, bucket, path, size, kind, ref_id, site_id):
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO supa_objects(bucket,path,size,kind,ref_id,site_id,uploaded_at,deleted_at) VALUES (?,?,?,?,?,?,?,NULL) "
                       "ON CONFLICT(bucket,path) DO UPDATE SET size=excluded.size, uploaded_at=excluded.uploaded_at, deleted_at=NULL",
                       (bucket, path, size, kind, ref_id, site_id, now()))

    def find(self, kind: str, ref_id: str) -> dict | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM supa_objects WHERE kind=? AND ref_id=? AND deleted_at IS NULL", (kind, ref_id)).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict:
        with self.store.connect() as db:
            rows = db.execute("SELECT kind, COUNT(*) n, COALESCE(SUM(size),0) bytes FROM supa_objects WHERE deleted_at IS NULL GROUP BY kind").fetchall()
            removed = db.execute("SELECT COUNT(*) FROM supa_objects WHERE deleted_at IS NOT NULL").fetchone()[0]
        return dict(objects={r["kind"]: dict(count=r["n"], bytes=r["bytes"]) for r in rows}, deletedByRetention=removed,
                    uploads=self.uploads, failures=self.failures)

    def our_bytes(self) -> int:
        with self.store.connect() as db:
            return int(db.execute("SELECT COALESCE(SUM(size),0) FROM supa_objects WHERE deleted_at IS NULL").fetchone()[0])

    # ---- uploads ----------------------------------------------------------------------------------------------

    def _put(self, bucket: str, path: str, data: bytes, content_type: str, kind: str, ref_id: str, site_id: str | None) -> bool:
        if self.find(kind, ref_id):
            return True
        ok, cap = self.budget.allow_upload(len(data))
        if not ok:
            self.budget.refuse(cap, f"{kind} {ref_id} ({len(data)} bytes) kept local only.")
            return False
        try:
            self.supa.upload(bucket, path, data, content_type)
        except Exception as error:
            self.failures += 1
            self.on_event("Supabase Storage upload failed", f"{bucket}/{path}: {type(error).__name__}: {str(error)[:200]}")
            return False
        self._record(bucket, path, len(data), kind, ref_id, site_id)
        self.budget.add_storage(len(data))
        self.budget.note_upload_size(len(data))
        self.uploads += 1
        return True

    def upload_frame(self, frame: dict, frames_dir: Path) -> bool:
        frame_id, site = frame.get("id") or "", frame.get("siteId") or "site"
        path = frames_dir / f"{frame_id}.jpg"
        if not frame_id.startswith("eyf-") or not path.is_file():
            return False
        data = path.read_bytes()
        ok = self._put("eye-frames", f"{site}/{frame_id}.jpg", data, "image/jpeg", "eye_frame", frame_id, site)
        if ok and not self.budget.transforms_available():
            self.upload_thumb(frame_id, site, data)
        self.retention()
        return ok

    def upload_thumb(self, frame_id: str, site: str, data: bytes | None = None, frames_dir: Path | None = None) -> bool:
        if self.find("eye_thumb", frame_id):
            return True
        if data is None and frames_dir is not None and (frames_dir / f"{frame_id}.jpg").is_file():
            data = (frames_dir / f"{frame_id}.jpg").read_bytes()
        small = thumbnail(data) if data else None
        if not small:
            return False
        return self._put("eye-frames", f"{site}/thumbs/{frame_id}.jpg", small, "image/jpeg", "eye_thumb", frame_id, site)

    def upload_evidence(self, attestation: dict, files_dir: Path) -> int:
        site = attestation.get("propertyId") or "site"
        uploaded = 0
        for digest in attestation.get("evidenceHashes") or []:
            if not isinstance(digest, str) or len(digest) != 64 or self.find("evidence", digest):
                continue
            matches = [p for p in files_dir.glob(f"{digest}*") if p.is_file()]
            if not matches:
                continue
            path = matches[0]
            content_type = EVIDENCE_TYPES.get(path.suffix.lower(), "application/octet-stream")
            if self._put("evidence", f"{site}/{path.name}", path.read_bytes(), content_type, "evidence", digest, site):
                uploaded += 1
        return uploaded

    def upload_evidence_record(self, evidence: dict, files_dir: Path) -> bool:
        """An imported evidence record's original file (`evidence/<site>/<evidenceId><ext>`), e.g. a seeded observation."""
        name = evidence.get("_path") or ""
        evidence_id = evidence.get("id") or ""
        if evidence_id and self.find("evidence_record", evidence_id):
            return True
        path = files_dir / name
        if not name or not evidence_id or "/" in name or ".." in name or not path.is_file():
            return False
        site = evidence.get("_propertyId") or evidence.get("propertyId") or "site"
        content_type = EVIDENCE_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return self._put("evidence", f"{site}/{evidence_id}{path.suffix.lower()}", path.read_bytes(), content_type, "evidence_record", evidence_id, site)

    # ---- retention --------------------------------------------------------------------------------------------

    def retention(self) -> int:
        """Past 80 % of the storage cap, delete this backend's oldest eye frames (and their thumbnails) from the bucket
        until usage is under 70 %. Local copies stay; evidence is never deleted."""
        cap = self.budget.cap("storage_mb") * 1024 * 1024
        if cap <= 0 or self.budget.storage_bytes() <= RETENTION_HIGH * cap:
            return 0
        removed = 0
        target = RETENTION_LOW * cap
        while self.budget.storage_bytes() > target:
            excess = self.budget.storage_bytes() - target
            with self.store.connect() as db:
                candidates = db.execute("SELECT bucket, path, size, ref_id FROM supa_objects WHERE kind IN ('eye_frame','eye_thumb') AND deleted_at IS NULL "
                                        "ORDER BY uploaded_at, rowid LIMIT 200").fetchall()
            rows, freed_plan = [], 0
            for row in candidates:  # only as many of the oldest as it takes to get back under the low-water mark
                rows.append(row)
                freed_plan += int(row["size"])
                if freed_plan >= excess:
                    break
            if not rows:
                break
            paths = [r["path"] for r in rows]
            try:
                self.supa.remove("eye-frames", paths)
            except Exception as error:
                self.on_event("Supabase Storage retention failed", f"{type(error).__name__}: {str(error)[:200]}")
                break
            with self.store.lock, self.store.connect() as db:
                db.executemany("UPDATE supa_objects SET deleted_at=? WHERE bucket=? AND path=?", [(now(), r["bucket"], r["path"]) for r in rows])
            freed = sum(int(r["size"]) for r in rows)
            self.budget.add_storage(-freed)
            removed += len(rows)
            with self.lock:
                for r in rows:
                    for key in [k for k in self.signed if k[1] == r["path"]]:
                        self.signed.pop(key, None)
        if removed:
            self.deleted += removed
            self.on_event("Supabase Storage retention", f"Deleted {removed} oldest eye-frame object(s) from the bucket (local copies kept).")
        return removed

    # ---- signed URLs ------------------------------------------------------------------------------------------

    def _sign(self, bucket: str, path: str, size: int, transform: dict | None = None, copies: int = 1) -> str | None:
        """A signed URL (15 minutes), reused for 10 minutes so browsers can cache the image by URL. Egress is charged when
        a URL is minted (size x the number of browsers expected to fetch it); a cached URL costs nothing more."""
        key = (bucket, path, bool(transform))
        moment = self.clock()
        with self.lock:
            cached = self.signed.get(key)
        if cached and cached[0] > moment:
            return cached[1]
        if not self.budget.spend_egress(size * max(1, int(copies))):
            self.budget.refuse("egress_mb_day", f"Signed URL for {bucket}/{path} withheld; serving the local file.")
            return None
        try:
            url = self.supa.sign(bucket, path, SIGNED_SECONDS, transform)
        except Exception as error:
            self.on_event("Supabase signed URL failed", f"{bucket}/{path}: {type(error).__name__}")
            return None
        with self.lock:
            self.signed[key] = (moment + SIGN_CACHE_SECONDS, url)
            if len(self.signed) > 2000:
                for old in list(self.signed)[:500]:
                    self.signed.pop(old, None)
        return url

    def frame_url(self, frame_id: str, copies: int = 1) -> str | None:
        record = self.find("eye_frame", frame_id)
        return self._sign(record["bucket"], record["path"], record["size"], copies=copies) if record else None

    def thumb_url(self, frame_id: str, site: str | None = None, frames_dir: Path | None = None, copies: int = 1) -> str | None:
        record = self.find("eye_frame", frame_id)
        if not record:
            return None
        if self.budget.transforms_available() and self.budget.allow_transform(record["path"]):
            url = self._sign(record["bucket"], record["path"], max(1, record["size"] // 6),
                             dict(width=THUMB_WIDTH, resize="contain", quality=70), copies=copies)
            if url:
                return url
        thumb = self.find("eye_thumb", frame_id)
        if not thumb and frames_dir is not None:
            self.upload_thumb(frame_id, site or record.get("site_id") or "site", frames_dir=frames_dir)
            thumb = self.find("eye_thumb", frame_id)
        return self._sign(thumb["bucket"], thumb["path"], thumb["size"], copies=copies) if thumb else None

    def evidence_url(self, digest: str) -> str | None:
        record = self.find("evidence", digest)
        return self._sign(record["bucket"], record["path"], record["size"]) if record else None
