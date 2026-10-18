"""Vision pipeline tests. No browser, backend or paid API needed for the default set.

    vision/.venv/bin/python -m unittest discover -s vision/tests -v
    VISION_TEST_MODEL=1 vision/.venv/bin/python -m unittest discover -s vision/tests -v   # + real V-JEPA 2

The Chrome test drives real headless Chrome against tests/mock_stack.py (a local stand-in for the
frontend /capture route and backend); it is skipped when Chrome is not installed. The --live
explain test points the Anthropic SDK at the mock (ANTHROPIC_BASE_URL), so nothing is sent out.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VISION = HERE.parent
sys.path[:0] = [str(VISION), str(HERE), str(VISION / "fixtures")]

import capture  # noqa: E402
import common  # noqa: E402
import explain  # noqa: E402
import jepa  # noqa: E402
import make_fixture  # noqa: E402
import mock_stack  # noqa: E402
import post  # noqa: E402
import scoring  # noqa: E402
from cdp import DEFAULT_CHROME  # noqa: E402

RUN_MODEL = os.environ.get("VISION_TEST_MODEL") == "1"


def unit(x):
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def peer_maps(n=5, noise=0.05, seed=0, d=32):
    rng = np.random.default_rng(seed)
    base = rng.normal(size=(8, 16, 16, d))
    return np.stack([unit(base + noise * rng.normal(size=base.shape)) for _ in range(n)]).astype(np.float32), rng


class MockStack:
    def __enter__(self):
        mock_stack.POSTS.clear()
        self.srv = mock_stack.serve(0)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()


def quiet_call(fn, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(argv)
            code = 0
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TestScoring(unittest.TestCase):
    def test_outlier_flagged(self):
        maps, rng = peer_maps()
        odd = unit(rng.normal(size=maps.shape[1:]))[None].astype(np.float32)
        res, thr = scoring.score_site(np.concatenate([maps, odd]))
        self.assertEqual([r.status for r in res], ["fixed"] * 5 + ["not_fixed"])
        self.assertGreater(res[-1].score, thr["value"])
        self.assertEqual(thr["method"], "median + k * MAD")

    def test_identical_peers_flag_nothing(self):
        maps, _ = peer_maps(noise=0.0)
        res, thr = scoring.score_site(maps)
        self.assertTrue(all(r.status == "fixed" for r in res))
        self.assertGreaterEqual(thr["madEffective"], scoring.ABS_FLOOR)

    def test_too_few_peers_is_uncertain(self):
        maps, _ = peer_maps(n=2)
        res, _ = scoring.score_site(maps)
        self.assertTrue(all(r.status == "uncertain" for r in res))

    def test_reference_defect_label_makes_uncertain(self):
        maps, rng = peer_maps()
        leak_like = unit(maps[0] + 0.01 * rng.normal(size=maps.shape[1:]))[None].astype(np.float32)
        res, _ = scoring.score_site(maps, {"leak": np.repeat(leak_like, 2, axis=0)})
        self.assertEqual(res[0].status, "uncertain")
        self.assertEqual(res[0].reference["nearestLabel"], "leak")

    def test_normal_reference_adds_to_score(self):
        maps, _ = peer_maps()
        res0, _ = scoring.score_site(maps)
        res1, _ = scoring.score_site(maps, {"fixed": maps[:2]})
        self.assertGreater(sum(r.ref_term for r in res1), 0)
        self.assertGreaterEqual(res1[3].score, res0[3].score)

    def test_peak_cell(self):
        g = np.zeros((16, 16))
        g[14, 1] = 1
        self.assertEqual(scoring.peak_cell(g)["where"], "bottom-left")


class TestFixturePipeline(unittest.TestCase):
    """Six numpy clips (five solid-colour peers, one noise outlier) through jepa -> explain -> post."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="vision-test-"))
        cls.clips = cls.tmp / "clips"
        make_fixture.make(cls.clips)
        cls.results = cls.tmp / "fixture.json"
        cls.out = jepa.run("fixture", cls.clips, cls.results, cls.tmp / "no-ref", embedder_name="pixel-stats",
                           quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_outlier_flagged(self):
        status = {v["assetTag"]: v["status"] for v in self.out["valves"]}
        self.assertEqual(status.pop(make_fixture.OUTLIER), "not_fixed")
        self.assertTrue(all(s == "fixed" for s in status.values()), status)

    def test_contract_shape(self):
        for v in self.out["valves"]:
            for key in ("assetTag", "status", "score", "threshold", "model", "frames", "inspectedBy"):
                self.assertIn(key, v)
            self.assertEqual(len(v["frames"]), 16)
        self.assertEqual(self.out["inspectedBy"], "fixture-engineer")
        self.assertIn("not a trained defect classifier", self.out["honesty"])
        self.assertIn("TEST RUN", self.out["honesty"])

    def test_explain_dry_run_writes_request_only(self):
        req_dir = self.tmp / "req"
        env = {k: os.environ.pop(k) for k in ("ANTHROPIC_API_KEY",) if k in os.environ}
        try:
            code, out, _ = quiet_call(explain.main, ["fixture", "--results", str(self.results), "--frames-root",
                                                     str(self.clips), "--requests-dir", str(req_dir), "--no-backend"])
        finally:
            os.environ.update(env)
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        req = json.loads((req_dir / f"fixture__{make_fixture.OUTLIER}.json").read_text())
        body = req["body"]
        self.assertTrue(req["dryRun"])
        self.assertEqual(body["model"], "claude-opus-5-5")
        imgs = [c for c in body["messages"][0]["content"] if c["type"] == "image"]
        self.assertEqual(len(imgs), 4)
        self.assertEqual(set(body["output_config"]["format"]["schema"]["required"]),
                         {"finding", "evidence", "confidence", "recommendedAction"})
        res = json.loads(self.results.read_text())
        flagged = [v for v in res["valves"] if v["status"] != "fixed"]
        self.assertTrue(all(v["explanationStatus"] == "dry_run" and v["explanation"] is None for v in flagged))

    def test_explain_live_against_mock(self):
        live = self.tmp / "live.json"
        shutil.copy(self.results, live)
        with MockStack() as m:
            old = {k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
            os.environ.update(ANTHROPIC_BASE_URL=m.url, ANTHROPIC_API_KEY="test-not-a-real-key")
            try:
                code, _, err = quiet_call(explain.main, ["fixture", "--live", "--results", str(live), "--frames-root",
                                                         str(self.clips), "--requests-dir", str(self.tmp / "req2"),
                                                         "--no-backend"])
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual(code, 0, err)
        v = next(v for v in json.loads(live.read_text())["valves"] if v["assetTag"] == make_fixture.OUTLIER)
        self.assertEqual(v["explanationStatus"], "done")
        self.assertTrue(v["explanation"]["finding"].startswith("Mock:"))
        self.assertIn("4 images", v["explanation"]["evidence"][0])

    def test_post_to_mock(self):
        with MockStack() as m:
            code, out, err = quiet_call(post.main, ["fixture", "--backend", m.url, "--results", str(self.results)])
            self.assertEqual(code, 0, err)
            self.assertEqual(len(mock_stack.POSTS), 1)
            self.assertEqual(mock_stack.POSTS[0]["siteId"], "fixture")
            self.assertEqual(mock_stack.POSTS[0]["_actor"], "fixture-engineer")

    def test_post_missing_route_exit_3(self):
        with MockStack() as m:
            code, _, err = quiet_call(post.main, ["nowhere", "--backend", m.url + "/nope", "--results", str(self.results)])
        self.assertEqual(code, 3, err)


class TestMixedSources(unittest.TestCase):
    def test_mixed_frame_sources_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision-mixed-"))
        try:
            make_fixture.make(tmp)
            meta = json.loads((tmp / "FX-02" / "meta.json").read_text())
            (tmp / "FX-02" / "meta.json").write_text(json.dumps({**meta, "source": "eye"}))
            with self.assertRaises(common.VisionError) as ctx:
                jepa.run("fixture", tmp, tmp / "r.json", tmp / "no-ref", embedder_name="pixel-stats", quiet=True)
            self.assertIn("different frame sources", str(ctx.exception))
            out = jepa.run("fixture", tmp, tmp / "r.json", tmp / "no-ref", embedder_name="pixel-stats", quiet=True,
                           allow_mixed=True)
            self.assertEqual(len(out["frameSource"]), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEyeSource(unittest.TestCase):
    """--source eye against the mock agent eye: actor header, orbit body, downloads, defect echo."""

    def test_eye_orbit_capture(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision-eye-"))
        try:
            with MockStack() as m:
                mock_stack.EYE_CALLS.clear()
                code, out, err = quiet_call(capture.main, ["mock-site", "--source", "eye", "--backend", m.url,
                                                           "--defect", "MV-503=leak", "--out-root", str(tmp)])
                calls = list(mock_stack.EYE_CALLS)
            self.assertEqual(code, 0, err)
            self.assertIn("via eye", out)
            self.assertEqual(len(calls), 5)
            self.assertTrue(all(c["actor"] == "mock-engineer" for c in calls))
            self.assertEqual(calls[0]["body"], {"action": "orbit", "params": {"assetTag": "MV-501", "frames": 16}})
            self.assertEqual(calls[2]["body"]["params"].get("defect"), "leak")
            manifest = json.loads((tmp / "manifest.json").read_text())
            self.assertEqual(manifest["frameSource"], ["eye"])
            self.assertEqual(manifest["requestedBy"], "mock-engineer")
            meta = json.loads((tmp / "MV-503" / "meta.json").read_text())
            self.assertEqual((meta["source"], meta["actor"], meta["size"]), ("eye", "mock-engineer", [640, 400]))
            self.assertTrue(meta["synthetic"])
            self.assertTrue(meta["defectConfirmed"])
            self.assertEqual(len(list((tmp / "MV-501").glob("f*.jpg"))), 16)
            res = jepa.run("mock-site", tmp, tmp / "r.json", tmp / "no-ref", embedder_name="pixel-stats", quiet=True)
            self.assertEqual(res["inspectedBy"], "mock-engineer")
            self.assertEqual(res["frameSource"], "eye 640x400")
            if RUN_MODEL:
                res = jepa.run("mock-site", tmp, tmp / "m.json", tmp / "no-ref", quiet=True)
                status = {v["assetTag"]: v["status"] for v in res["valves"]}
                self.assertEqual(status["MV-503"], "not_fixed", status)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_engineer_ids(self):
        self.assertEqual(common.engineer_for("myer-plant"), "myer-engineer")
        self.assertEqual(common.engineer_for("bristol-pumps"), "bristol-engineer")


class TestAssets(unittest.TestCase):
    def test_two_d_pins_fail_clearly(self):
        assets = [common.normalise_asset({"tag": "V-1", "kind": "valve", "pin": {"x": 0.2, "y": 0.4}})]
        with self.assertRaises(common.VisionError) as ctx:
            common.valves_with_pins(assets, "myer-plant")
        self.assertIn("3-D world pin", str(ctx.exception))

    def test_three_d_pin_list_or_dict(self):
        a = common.normalise_asset({"tag": "V-1", "kind": "Valve", "pin": [1, 2, 3]})
        b = common.normalise_asset({"assetTag": "V-2", "kind": "valve", "pin": {"x": 1, "y": 2, "z": 3}})
        self.assertEqual(a["pin"], {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertEqual(len(common.valves_with_pins([a, b], "s")), 2)

    def test_bad_defect_arg(self):
        with self.assertRaises(common.VisionError):
            capture.parse_defects(["V-1=rusty"])
        self.assertEqual(capture.parse_defects(["V-1=leak"]), {"V-1": "leak"})


@unittest.skipUnless(Path(DEFAULT_CHROME).exists(), "Google Chrome not installed")
class TestCaptureChrome(unittest.TestCase):
    """Real headless Chrome (SwiftShader) over CDP against the mock capture route."""

    def test_capture_mock_site(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision-cap-"))
        try:
            with MockStack() as m:
                code, out, err = quiet_call(capture.main, ["mock-site", "--base", m.url, "--backend", m.url,
                                                           "--defect", "MV-503=leak", "--out-root", str(tmp),
                                                           "--timeout", "60"])
            self.assertEqual(code, 0, err)
            manifest = json.loads((tmp / "manifest.json").read_text())
            self.assertEqual(manifest["tags"], [f"MV-50{i}" for i in range(1, 6)])
            self.assertEqual(manifest["defects"], {"MV-503": "leak"})
            meta = json.loads((tmp / "MV-503" / "meta.json").read_text())
            self.assertTrue(meta["synthetic"])
            self.assertEqual(meta["size"], [256, 256])
            self.assertEqual(len(list((tmp / "MV-501").glob("f*.jpg"))), 16)
            self.assertEqual(manifest["frameSource"], ["capture-route"])
            if RUN_MODEL:
                res = jepa.run("mock-site", tmp, tmp / "mock.json", tmp / "no-ref", quiet=True)
                status = {v["assetTag"]: v["status"] for v in res["valves"]}
                self.assertEqual(status["MV-503"], "not_fixed", status)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_eye_404_falls_back_to_capture_route(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision-fallback-"))
        try:
            with MockStack() as m:
                code, out, err = quiet_call(capture.main, ["noeye-site", "--source", "eye", "--base", m.url,
                                                           "--backend", m.url, "--out-root", str(tmp), "--only",
                                                           "MV-501,MV-502,MV-503", "--timeout", "60"])
            self.assertEqual(code, 0, err)
            self.assertIn("falling back to the /capture route", err)
            manifest = json.loads((tmp / "manifest.json").read_text())
            self.assertEqual((manifest["requestedSource"], manifest["frameSource"]), ("eye", ["capture-route"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(RUN_MODEL, "set VISION_TEST_MODEL=1 to load V-JEPA 2")
class TestRealModelFixture(unittest.TestCase):
    def test_vjepa2_flags_fixture_outlier(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision-model-"))
        try:
            make_fixture.make(tmp / "clips")
            res = jepa.run("fixture", tmp / "clips", tmp / "fixture.json", tmp / "no-ref", quiet=True)
            status = {v["assetTag"]: v["status"] for v in res["valves"]}
            self.assertEqual(status.pop(make_fixture.OUTLIER), "not_fixed")
            self.assertTrue(all(s == "fixed" for s in status.values()), status)
            self.assertEqual(res["model"]["id"], "facebook/vjepa2-vitl-fpc64-256")
            print(f"\n[model] device={res['timings']['device']} load={res['timings']['modelLoadSeconds']}s "
                  f"first={res['timings']['firstClipSeconds']}s warm={res['timings']['meanWarmClipSeconds']}s/clip",
                  file=sys.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
