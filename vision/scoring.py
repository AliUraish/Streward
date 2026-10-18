"""Anomaly scoring and thresholding for valve clip embeddings (pure numpy, no model).

Two modes. PEER mode (no baselines) compares each valve with the other valves at its site;
BASELINE mode (vision/reference/<site>/fixed/<tag>/ holds an accepted-good capture of every valve)
compares each valve with its own baseline, which is what "fixed / not fixed" means after a repair.
On the real Myer scan the location-to-location peer spread (~0.44) swamps a synthetic leak (~0.07
from its own clean render), so peer mode only works when the valves' views look alike.

Embedding of a clip = V-JEPA 2 encoder token map G of shape (T', H', W', D) = (8, 16, 16, 1024)
for 16 frames at 256x256, each token L2-normalised. Every capture is an orbit centred on the pin,
so token (t, y, x) of one valve and token (t, y, x) of another look at the same place relative
to their pins; that makes a position-aligned comparison meaningful.

loo_i      = sum_{t,y,x} w(y,x) * cos_dist(G_i[t,y,x], M_i[t,y,x]) / sum w
             where M_i = element-wise median of the other valves' token maps (leave-one-out),
             re-normalised per token, and w is a centred Gaussian (sigma 6 patches) so the area
             around the pin counts more than the background.
ref_i      = mean of the k nearest (same distance) 'normal' reference clips, if vision/reference/
             has a normal label (fixed/ok/normal/good/healthy); 0 otherwise.
score_i    = loo_i + ref_i

threshold      = max(median + K * MAD_eff,              statistical bar (Hampel identifier, K = 3.0)
                     (1 + REL_EFFECT) * median)          practical bar: at least 5 % above the median
uncertainAbove = min(median + K_UNCERTAIN * MAD_eff, threshold)   (K_UNCERTAIN = 2.0)
MAD_eff        = max(1.4826 * MAD(scores), ABS_FLOOR)   (ABS_FLOOR = 0.005)

1.4826 * MAD estimates a standard deviation under normality, so K = 3 is the robust analogue of
"three sigma above the site's typical valve". With five valves the MAD can collapse towards 0 when
three scores coincide; ABS_FLOOR (about 1 % of the peer distance seen on the real Myer scan) keeps
that from flagging noise, and the practical bar stops a statistically clear but tiny difference
from reading as not_fixed (it lands in uncertain instead). An earlier rule floored MAD at 10 % of
the median; on the real scan that floor (0.044) was ten times the actual spread (MAD 0.003) and hid
the injected leak, and a floor scaled by the score level, not by its spread, is the wrong noise
model, so it was replaced.

status: score > threshold -> not_fixed; score > uncertainAbove -> uncertain; else fixed.
"fixed" only means "looks like its peers": no evidence of a defect, not proof of soundness.
With fewer than 3 valve clips and no reference set, every valve is 'uncertain'.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

K_DEFAULT = 3.0
K_UNCERTAIN_DEFAULT = 2.0
MAD_SCALE = 1.4826
ABS_FLOOR = 0.005
REL_EFFECT = 0.05
KNN_K = 3
SIGMA_PATCHES = 6.0
NORMAL_LABELS = {"fixed", "ok", "normal", "good", "healthy"}
MIN_PEERS = 3


def l2n(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=axis, keepdims=True), 1e-12)


def weight_map(h: int, w: int, region: str = "centre", sigma: float = SIGMA_PATCHES) -> np.ndarray:
    if region == "full":
        return np.ones((h, w), dtype=np.float64)
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    return np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))


def patch_distance(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> tuple[float, np.ndarray]:
    """Weighted mean cosine distance between two unit token maps (T,H,W,D); also the (H,W) map."""
    d = 1.0 - np.einsum("thwd,thwd->thw", a, b, optimize=True).astype(np.float64)
    grid = d.mean(axis=0)
    return float((grid * w).sum() / w.sum()), grid


def loo_patch_scores(maps: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    n = maps.shape[0]
    scores, grids = np.zeros(n), []
    for i in range(n):
        med = l2n(np.median(np.delete(maps, i, axis=0), axis=0))
        scores[i], g = patch_distance(maps[i], med, w)
        grids.append(g)
    return scores, grids


def knn_reference(maps: np.ndarray, refs: dict[str, np.ndarray], w: np.ndarray, k: int = KNN_K) -> list[dict]:
    """Per clip: mean distance to the k nearest reference clips of each label, and the kNN-vote label."""
    rows = []
    for g in maps:
        per_label, pool = {}, []
        for label, R in refs.items():
            d = np.sort([patch_distance(g, r, w)[0] for r in R])
            per_label[label] = round(float(np.mean(d[: min(k, len(d))])), 6)
            pool += [(float(x), label) for x in d]
        pool.sort()
        votes: dict[str, int] = {}
        for _, label in pool[:k]:
            votes[label] = votes.get(label, 0) + 1
        nearest = max(votes, key=lambda lb: (votes[lb], -per_label[lb])) if votes else None
        rows.append({"distanceByLabel": per_label, "nearestLabel": nearest, "votes": votes})
    return rows


def robust_threshold(scores, k: float = K_DEFAULT, k_uncertain: float = K_UNCERTAIN_DEFAULT,
                     abs_floor: float = ABS_FLOOR, rel_effect: float = REL_EFFECT) -> dict:
    s = np.asarray(scores, dtype=np.float64)
    med = float(np.median(s))
    mad = float(np.median(np.abs(s - med)))
    mad_eff = max(MAD_SCALE * mad, abs_floor)
    statistical = med + k * mad_eff
    practical = (1.0 + rel_effect) * med
    value = max(statistical, practical)
    return {
        "method": "max(median + k * MAD, (1 + minEffect) * median)", "k": k, "kUncertain": k_uncertain,
        "median": med, "mad": mad, "madScaled": MAD_SCALE * mad, "madFloor": abs_floor, "madEffective": mad_eff,
        "minEffect": rel_effect, "statisticalBar": statistical, "practicalBar": practical,
        "value": value, "uncertainAbove": min(med + k_uncertain * mad_eff, value), "n": int(s.size),
    }


def classify(score: float, thr: dict) -> str:
    if score > thr["value"]:
        return "not_fixed"
    if score > thr["uncertainAbove"]:
        return "uncertain"
    return "fixed"


@dataclass
class Scored:
    score: float
    status: str
    loo: float
    ref_term: float
    reference: dict | None
    reason: str
    grid: np.ndarray  # (H', W') time-averaged patch distance to the peer median


def score_site(maps: np.ndarray, refs: dict[str, np.ndarray] | None = None, k: float = K_DEFAULT,
               k_uncertain: float = K_UNCERTAIN_DEFAULT, region: str = "centre",
               baselines: np.ndarray | None = None) -> tuple[list[Scored], dict]:
    """maps: (N, T, H, W, D) unit token maps for one site. Returns (per-clip results, threshold).

    Peer mode (default): score = leave-one-out peer distance (+ k-NN distance to 'normal' references).
    Baseline mode (baselines given, aligned with maps): score = distance from each valve's clip to its
    OWN accepted-good baseline clip, i.e. "has this valve changed since it was last known good".
    """
    maps = np.asarray(maps, dtype=np.float32)
    n, _, h, wd, _ = maps.shape
    w = weight_map(h, wd, region)
    refs = {lb: np.asarray(R, dtype=np.float32) for lb, R in (refs or {}).items() if len(R)}
    normal = {lb: R for lb, R in refs.items() if lb.lower() in NORMAL_LABELS}

    if n >= 2:
        loo, grids = loo_patch_scores(maps, w)
    else:
        loo, grids = np.zeros(n), [np.zeros((h, wd)) for _ in range(n)]
    knn = knn_reference(maps, refs, w) if refs else [None] * n
    ref_term = np.zeros(n)
    mode = "peer"
    if baselines is not None:
        mode = "baseline"
        pairs = [patch_distance(maps[i], np.asarray(baselines[i], dtype=np.float32), w) for i in range(n)]
        ref_term = np.array([d for d, _ in pairs])
        grids = [g for _, g in pairs]
        scores = ref_term.copy()
    else:
        if normal:
            ref_term = np.array([min(r["distanceByLabel"].values()) for r in knn_reference(maps, normal, w)])
        scores = loo + ref_term
    thr = robust_threshold(scores, k=k, k_uncertain=k_uncertain)
    thr["region"] = region if region == "full" else f"centre-weighted (gaussian sigma {SIGMA_PATCHES:g} patches)"
    thr["mode"] = mode
    peer_word = "its own baseline" if mode == "baseline" else "peer valves"

    results = []
    for i in range(n):
        s = float(scores[i])
        if n < MIN_PEERS and not refs and mode == "peer":
            status, reason = "uncertain", f"only {n} valve clip(s); a peer comparison needs at least {MIN_PEERS}"
        else:
            status = classify(s, thr)
            reason = {
                "not_fixed": f"score {s:.4f} > threshold {thr['value']:.4f} (median {thr['median']:.4f}"
                             + (f"; {(s / thr['median'] - 1) * 100:.0f} % above it)" if thr["median"] >= ABS_FLOOR else ")"),
                "uncertain": f"score {s:.4f} between {thr['uncertainAbove']:.4f} and threshold {thr['value']:.4f}",
                "fixed": f"score {s:.4f} <= {thr['uncertainAbove']:.4f}; consistent with {peer_word}",
            }[status]
            if mode == "baseline":
                reason = "change since the baseline capture: " + reason
            near = knn[i]["nearestLabel"] if knn[i] else None
            if near and near.lower() not in NORMAL_LABELS and status == "fixed":
                status, reason = "uncertain", reason + f"; but the nearest labelled reference is '{near}'"
        results.append(Scored(score=s, status=status, loo=float(loo[i]), ref_term=float(ref_term[i]),
                              reference=knn[i], reason=reason, grid=grids[i]))
    return results, thr


def peak_cell(grid: np.ndarray) -> dict:
    """Where on the 16x16 patch grid the clip differs most from its peers (row 0 = top)."""
    y, x = np.unravel_index(int(np.argmax(grid)), grid.shape)
    h, w = grid.shape
    vert = "top" if y < h / 3 else "bottom" if y >= 2 * h / 3 else "middle"
    horiz = "left" if x < w / 3 else "right" if x >= 2 * w / 3 else "centre"
    return {"row": int(y), "col": int(x), "where": f"{vert}-{horiz}", "value": round(float(grid[y, x]), 4)}
