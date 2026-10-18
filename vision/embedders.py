"""Clip embedders.

VJEPA2Embedder is the real one. PixelStatsEmbedder is a cheap, model-free baseline used only by
the unit tests to exercise the scoring logic without loading weights; results produced with it
are labelled as such and must never be shown as a model result.
"""
from __future__ import annotations

import os
import time

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

MODEL_ID = "facebook/vjepa2-vitl-fpc64-256"
# Hugging Face commit pinned on 2026-10-17 (config.json transformers_version 4.53.0.dev0).
MODEL_REVISION = "b3c1679b7c34d3255ef3547f27c7b226aefab26f"


class PixelStatsEmbedder:
    """Per-patch colour mean/std on a 16x16 grid, frames averaged in pairs. Test-only; not a model.

    Returns the same shapes as VJEPA2Embedder so the scoring path is identical.
    """

    model_id = "pixel-stats-baseline (test only, not a model)"
    revision = None
    device = "cpu"
    pooling = "per-patch RGB mean/std, 16x16 grid, tubelet 2"
    library = "numpy"
    load_seconds = 0.0

    def embed(self, clip: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = clip.astype(np.float32) / 255.0                      # T,H,W,3
        t, h, w, _ = x.shape
        x = x[: t - t % 2].reshape(t // 2, 2, h, w, 3).mean(1)   # tubelet 2
        p = x.reshape(t // 2, 16, h // 16, 16, w // 16, 3)
        feats = np.concatenate([p.mean(axis=(2, 4)), p.std(axis=(2, 4)), np.full(p.shape[:1] + (16, 16, 1), 0.05)], -1)
        feats = feats / np.linalg.norm(feats, axis=-1, keepdims=True)
        pooled = feats.reshape(-1, feats.shape[-1]).mean(0)
        return (pooled / np.linalg.norm(pooled)).astype(np.float32), feats.astype(np.float32)


class VJEPA2Embedder:
    """V-JEPA 2 ViT-L encoder via Hugging Face transformers (AutoModel + AutoVideoProcessor).

    Official usage from the model card: processor(video, return_tensors="pt") then
    model.get_vision_features(pixel_values_videos) -> encoder last_hidden_state (B, N, 1024).
    With 16 frames, tubelet 2 and patch 16 on the 256x256 centre crop, N = 8 * 16 * 16 = 2048
    tokens ordered (time, row, col). embed() returns
      - pooled: L2-normalised mean of all tokens (1024,), reported as a diagnostic,
      - tokens: the (8, 16, 16, 1024) token map, each token L2-normalised, used for scoring.
    """

    pooling = "token map (8x16x16x1024, per-token L2) + mean-pooled diagnostic"

    def __init__(self, model_id: str = MODEL_ID, revision: str | None = MODEL_REVISION, device: str = "auto"):
        import torch
        import transformers
        from transformers import AutoModel, AutoVideoProcessor

        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.torch = torch
        self.model_id, self.revision, self.device = model_id, revision, device
        t = time.perf_counter()
        self.processor = AutoVideoProcessor.from_pretrained(model_id, revision=revision)
        self.model = AutoModel.from_pretrained(model_id, revision=revision).to(device).eval()
        self.load_seconds = time.perf_counter() - t
        cfg = self.model.config
        self.patch, self.tubelet, self.crop = cfg.patch_size, cfg.tubelet_size, cfg.crop_size
        self.library = f"transformers {transformers.__version__}, torch {torch.__version__}"

    def embed(self, clip: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        torch = self.torch
        video = torch.from_numpy(np.ascontiguousarray(clip)).permute(0, 3, 1, 2)  # T,C,H,W uint8
        pixels = self.processor(video, return_tensors="pt")["pixel_values_videos"].to(self.device)
        with torch.no_grad():
            tokens = self.model.get_vision_features(pixels)  # (1, N, D)
        if self.device == "mps":
            torch.mps.synchronize()
        tokens = tokens[0].float().cpu().numpy()
        side = self.crop // self.patch
        grid = tokens.reshape(pixels.shape[1] // self.tubelet, side, side, -1)
        pooled = tokens.mean(0)
        grid = grid / np.maximum(np.linalg.norm(grid, axis=-1, keepdims=True), 1e-12)
        return (pooled / np.linalg.norm(pooled)).astype(np.float32), grid.astype(np.float32)


def make_embedder(name: str, device: str = "auto", model_id: str = MODEL_ID, revision: str | None = MODEL_REVISION):
    if name == "vjepa2":
        return VJEPA2Embedder(model_id=model_id, revision=revision, device=device)
    if name == "pixel-stats":
        return PixelStatsEmbedder()
    raise ValueError(f"unknown embedder {name!r}")
