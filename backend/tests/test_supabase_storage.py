"""Supabase Storage: budget-guarded uploads, Pillow thumbnails, retention past 80 %, signed URLs and egress, Pro transforms."""
import io
import json
import os

import httpx
import pytest
from PIL import Image

from src.store import Store
from src.supa_budget import MB, Budget
from src.supa_client import Supa
from src.supa_storage import ObjectStore, thumbnail


def jpeg(width=640, height=400, noise=0, random_pixels=False) -> bytes:
    if random_pixels:  # incompressible, so a frame is ~100 KB like a real render
        image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    else:
        image = Image.new("RGB", (width, height), (40 + noise % 200, 90, 160))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, int] = {}
        self.calls = []

    def __call__(self, request: httpx.Request):
        path = request.url.path
        self.calls.append((request.method, path, request.content[:0] if request.method == "POST" and "/object/sign/" not in path else request.content))
        if request.method == "POST" and path.startswith("/storage/v1/object/sign/"):
            key = path.removeprefix("/storage/v1/object/sign/")
            body = json.loads(request.content)
            prefix = "/render/image/sign/" if body.get("transform") else "/object/sign/"
            return httpx.Response(200, json={"signedURL": f"{prefix}{key}?token=t{len(self.calls)}"})
        if request.method == "POST" and path.startswith("/storage/v1/object/"):
            self.objects[path.removeprefix("/storage/v1/object/")] = len(request.content)
            return httpx.Response(200, json={"Key": path})
        if request.method == "DELETE":
            for prefix in json.loads(request.content)["prefixes"]:
                self.objects.pop("eye-frames/" + prefix, None)
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "unexpected"})


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "data")
    frames = tmp_path / "frames"
    frames.mkdir()
    fake = FakeStorage()
    budget = Budget(store)
    objects = ObjectStore(Supa("https://example.supabase.co", "sb_secret_test", "sb_publishable_test", httpx.MockTransport(fake)), budget, store)
    return store, frames, fake, budget, objects


def frame(frames, index=0, size_noise=0, random_pixels=False):
    frame_id = f"eyf-{index:016x}"
    (frames / f"{frame_id}.jpg").write_bytes(jpeg(noise=size_noise + index, random_pixels=random_pixels))
    return dict(id=frame_id, siteId="myer-plant", seq=index)


def test_thumbnail_is_320_px_wide():
    small = thumbnail(jpeg(1280, 800))
    with Image.open(io.BytesIO(small)) as image:
        assert image.size == (320, 200)


def test_frame_upload_records_storage_and_a_pillow_thumbnail_on_free(setup):
    store, frames, fake, budget, objects = setup
    record = frame(frames)
    assert objects.upload_frame(record, frames)
    assert set(fake.objects) == {f"eye-frames/myer-plant/{record['id']}.jpg", f"eye-frames/myer-plant/thumbs/{record['id']}.jpg"}
    assert budget.storage_bytes() == sum(fake.objects.values())
    assert objects.upload_frame(record, frames)  # idempotent: no second upload
    assert len([c for c in fake.calls if c[0] == "POST" and "/sign/" not in c[1]]) == 2


def test_per_object_and_storage_caps_keep_frames_local(setup, monkeypatch):
    store, frames, fake, budget, objects = setup
    monkeypatch.setenv("SUPABASE_CAP_UPLOAD_MB", "0")
    assert not objects.upload_frame(frame(frames, 1), frames)
    assert budget.refusals_today("upload_mb") == 1 and not fake.objects
    monkeypatch.setenv("SUPABASE_CAP_UPLOAD_MB", "5")
    monkeypatch.setenv("SUPABASE_CAP_STORAGE_MB", "1")
    budget.add_storage(MB)
    assert not objects.upload_frame(frame(frames, 2), frames)
    assert budget.refusals_today("storage_mb") == 1


def test_retention_deletes_the_oldest_frames_past_80_percent_and_keeps_local_copies(setup, monkeypatch):
    store, frames, fake, budget, objects = setup
    monkeypatch.setenv("SUPABASE_CAP_STORAGE_MB", "1")
    uploaded = []
    for index in range(24):
        record = frame(frames, index, random_pixels=True)
        if objects.upload_frame(record, frames):
            uploaded.append(record["id"])
    assert budget.storage_bytes() <= 0.8 * MB + 64 * 1024  # never far past the high-water mark
    assert objects.deleted > 0 and objects.find("eye_frame", uploaded[0]) is None  # the oldest left the bucket
    assert objects.find("eye_frame", uploaded[-1]) is not None
    assert all((frames / f"{frame_id}.jpg").exists() for frame_id in uploaded)  # local copies stay
    assert sum(fake.objects.values()) == budget.storage_bytes()


def test_signed_urls_are_cached_and_egress_is_charged_once_per_minted_url(setup, monkeypatch):
    store, frames, fake, budget, objects = setup
    record = frame(frames)
    objects.upload_frame(record, frames)
    first = objects.frame_url(record["id"], copies=3)
    again = objects.frame_url(record["id"], copies=3)
    assert first == again and first.startswith("https://example.supabase.co/storage/v1/object/sign/eye-frames/")
    size = objects.find("eye_frame", record["id"])["size"]
    assert budget.counter("egress_bytes", "day") == 3 * size
    objects.signed.clear()
    monkeypatch.setenv("SUPABASE_CAP_EGRESS_MB_DAY", "0")
    assert objects.frame_url(record["id"]) is None and budget.refusals_today("egress_mb_day") == 1  # serve the local file instead


def test_pro_uses_image_transformations_until_the_origin_cap_then_pillow(setup, monkeypatch):
    store, frames, fake, budget, objects = setup
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    monkeypatch.setenv("SUPABASE_CAP_TRANSFORM_ORIGINS_MONTH", "1")
    first, second = frame(frames, 1), frame(frames, 2)
    assert objects.upload_frame(first, frames) and objects.upload_frame(second, frames)
    assert not any("/thumbs/" in key for key in fake.objects)  # no eager Pillow thumbnails on Pro
    assert "/render/image/sign/" in objects.thumb_url(first["id"], "myer-plant", frames)
    fallback = objects.thumb_url(second["id"], "myer-plant", frames)  # origin cap reached: Pillow thumbnail
    assert "/object/sign/eye-frames/myer-plant/thumbs/" in fallback
    assert budget.counter("transform_origins", "month") == 1


def test_evidence_files_upload_by_digest(setup, tmp_path):
    store, frames, fake, budget, objects = setup
    files = tmp_path / "files"
    files.mkdir()
    digest = "ab" * 32
    (files / f"{digest}.jpg").write_bytes(jpeg(100, 100))
    attestation = dict(propertyId="myer-plant", evidenceHashes=[digest, "not-a-digest"])
    assert objects.upload_evidence(attestation, files) == 1
    assert f"evidence/myer-plant/{digest}.jpg" in fake.objects
    assert objects.upload_evidence(attestation, files) == 0  # already there
    assert objects.evidence_url(digest).startswith("https://example.supabase.co/storage/v1/object/sign/evidence/")
