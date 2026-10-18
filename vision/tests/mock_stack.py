#!/usr/bin/env python3
"""Local stand-in for the three services the pipeline talks to, for offline tests only.

    vision/.venv/bin/python vision/tests/mock_stack.py --port 0   # prints "READY <port>"

- GET  /api/properties/<site>/scene              5 valves with 3-D pins + 1 pump (contract-3 shape)
- GET  /api/properties/<site>/components/<id>    one asset record
- POST /api/properties/<site>/inspections/vision echoes {accepted, valves}
- GET  /capture?site=&asset=&frames=&defect=     WebGL page honouring the capture contract
                                                 (window.__frames data URLs + window.__done)
- POST /api/eye/<site>/act {action:'orbit', params:{assetTag, frames}}  agent-eye stand-in (contract 4 §2):
                                                 returns frame records; 404 for sites named noeye-*
- GET  /api/eye/frames/<id>.jpg                  the 640x400 frames it drew
- POST /v1/messages                              canned Anthropic-shaped reply (no network, no cost)

Nothing here is a render of a real site; it only exercises the plumbing (CDP, SwiftShader WebGL,
frame decoding, request building, ingest POST).
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import math
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw

VALVES = [
    {"id": f"valve-0{i}", "tag": f"MV-50{i}", "name": f"Mock isolation valve {i}", "kind": "valve",
     "system": "Mechanical", "subsystem": "Hydronic distribution",
     "pin": {"x": -3.0 + 1.5 * i, "y": 2.4, "z": -0.6}, "pinSource": "estimated",
     "spec": {"type": "gate valve", "dn": 80, "pn": 16, "handwheel": True}}
    for i in range(1, 6)
]
ASSETS = VALVES + [{"id": "pump-01", "tag": "MP-101", "name": "Mock pump", "kind": "pump",
                    "pin": {"x": 0, "y": 0, "z": 0}, "pinSource": "estimated"}]
POSTS: list[dict] = []
EYE_CALLS: list[dict] = []
EYE_FRAMES: dict[str, bytes] = {}
_ids = itertools.count(1)


def eye_frame(tag: str, i: int, n: int, defect: str) -> bytes:
    """A 640x400 'eye' frame: a valve drawn from angle i/n of an orbit (flat shapes, test only)."""
    im = Image.new("RGB", (640, 400), (40, 42, 46))
    d = ImageDraw.Draw(im)
    a = 2 * math.pi * i / n
    cx, w = 320 + int(40 * math.sin(a)), int(110 + 30 * math.cos(a))
    d.rectangle([cx - 200, 190, cx + 200, 215], fill=(110, 114, 120))                      # pipe
    body = (150, 78, 35) if defect == "corrosion" else (140 + 2 * (sum(map(ord, tag)) % 5), 146, 152)
    d.rectangle([cx - w // 2, 150, cx + w // 2, 255], fill=body)                           # valve body
    d.rectangle([cx - 6, 95, cx + 6, 150], fill=(100, 100, 104))                           # stem
    if defect != "missing-handwheel":
        d.ellipse([cx - 60, 80, cx + 60, 105], fill=(190, 30, 25))                         # handwheel
    if defect == "leak":
        d.ellipse([cx - 140, 300, cx + 140, 360], fill=(12, 16, 22))                       # wet patch
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

CAPTURE_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>mock capture</title></head>
<body style="margin:0;background:#111"><canvas id="c" width="256" height="256"></canvas><script>
(function(){
const q = new URLSearchParams(location.search);
const frames = parseInt(q.get('frames') || '16', 10), defect = q.get('defect') || 'none';
const asset = q.get('asset') || '';
const seed = [...asset].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 7;
const gl = document.getElementById('c').getContext('webgl', {preserveDrawingBuffer: true});
if (!gl) { window.__error = 'no webgl'; return; }
const vs = `attribute vec3 p; attribute vec3 col; uniform float a; varying vec3 v;
 void main(){ float c=cos(a), s=sin(a); vec3 r=vec3(c*p.x+s*p.z, p.y, -s*p.x+c*p.z);
 gl_Position=vec4(r.x*0.6, r.y*0.6 - 0.1*r.z, r.z*0.1, 1.0); v=col; }`;
const fs = `precision mediump float; varying vec3 v; void main(){ gl_FragColor=vec4(v,1.0); }`;
function sh(t, src){ const o=gl.createShader(t); gl.shaderSource(o, src); gl.compileShader(o); return o; }
const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs));
gl.linkProgram(pr); gl.useProgram(pr);
const tris = [];
function box(x0,y0,z0,x1,y1,z1,c){ const P=[[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]];
 const F=[[0,1,2,3],[5,4,7,6],[4,0,3,7],[1,5,6,2],[3,2,6,7],[4,5,1,0]];
 F.forEach((f,i)=>{ const k=0.75+0.05*i; const cc=c.map(x=>x*k); [[f[0],f[1],f[2]],[f[0],f[2],f[3]]].forEach(t=>t.forEach(j=>tris.push(...P[j],...cc))); }); }
const steel = [0.55+0.02*seed, 0.58, 0.62], rust = [0.62, 0.30, 0.12];
box(-1.2,-0.15,-0.15, 1.2,0.15,0.15, [0.45,0.47,0.5]);            // pipe
box(-0.3,-0.35,-0.3, 0.3,0.35,0.3, defect==='corrosion'?rust:steel); // valve body
box(-0.05,0.35,-0.05, 0.05,0.75,0.05, [0.4,0.4,0.42]);              // stem
if (defect !== 'missing-handwheel') box(-0.4,0.75,-0.4, 0.4,0.82,0.4, [0.75,0.12,0.1]); // handwheel
if (defect === 'leak') box(-0.9,-0.9,-0.9, 0.9,-0.85,0.9, [0.05,0.07,0.1]);           // wet patch
const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(tris), gl.STATIC_DRAW);
const lp = gl.getAttribLocation(pr,'p'), lc = gl.getAttribLocation(pr,'col');
gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp,3,gl.FLOAT,false,24,0);
gl.enableVertexAttribArray(lc); gl.vertexAttribPointer(lc,3,gl.FLOAT,false,24,12);
gl.enable(gl.DEPTH_TEST);
const ua = gl.getUniformLocation(pr,'a'), out = [];
let i = 0;
function step(){
  gl.clearColor(0.16,0.17,0.18,1); gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.uniform1f(ua, 2*Math.PI*i/frames); gl.drawArrays(gl.TRIANGLES, 0, tris.length/6);
  out.push(gl.canvas.toDataURL('image/jpeg', 0.92)); i++;
  if (i < frames) requestAnimationFrame(step); else { window.__frames = out; window.__done = true; }
}
setTimeout(() => requestAnimationFrame(step), 300);
})();
</script></body></html>"""


def anthropic_reply(body: dict) -> dict:
    n_images = sum(1 for m in body.get("messages", []) for c in m.get("content", []) if c.get("type") == "image")
    text = json.dumps({"finding": "Mock: dark patch below the valve body (test reply, not a model).",
                       "evidence": [f"frame 1: mock evidence ({n_images} images received)"],
                       "confidence": "low", "recommendedAction": "Mock: inspect the valve gland for weeping."})
    return {"id": "msg_mock", "type": "message", "role": "assistant", "model": body.get("model"),
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 80}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, payload, ctype="application/json"):
        if isinstance(payload, bytes):
            data = payload
        else:
            data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/capture":
            return self._send(200, CAPTURE_HTML, "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/properties/([^/]+)/scene", u.path)
        if m:
            return self._send(200, {"siteId": m.group(1), "assets": ASSETS})
        m = re.fullmatch(r"/api/properties/([^/]+)/components/([^/]+)", u.path)
        if m:
            hit = next((a for a in ASSETS if a["id"] == m.group(2)), None)
            return self._send(200 if hit else 404, hit or {"detail": "not found"})
        if u.path == "/_posts":
            return self._send(200, POSTS)
        m = re.fullmatch(r"/api/eye/frames/([^/]+)\.jpg", u.path)
        if m and m.group(1) in EYE_FRAMES:
            return self._send(200, EYE_FRAMES[m.group(1)], "image/jpeg")
        self._send(404, {"detail": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        m = re.fullmatch(r"/api/properties/([^/]+)/inspections/vision", u.path)
        if m:
            POSTS.append({**body, "_actor": self.headers.get("X-Steward-Actor")})
            return self._send(201, {"accepted": True, "siteId": m.group(1), "valves": len(body.get("valves", []))})
        m = re.fullmatch(r"/api/eye/([^/]+)/act", u.path)
        if m:
            site = m.group(1)
            if site.startswith("noeye"):
                return self._send(404, {"detail": "Not Found"})
            actor = self.headers.get("X-Steward-Actor")
            EYE_CALLS.append({"site": site, "actor": actor, "body": body})
            params = body.get("params") or {}
            if body.get("action") != "orbit" or not actor:
                return self._send(400, {"detail": "orbit with X-Steward-Actor expected"})
            n, tag, defect = int(params.get("frames", 16)), params.get("assetTag", ""), params.get("defect", "none")
            out = []
            for i in range(n):
                fid = f"f{next(_ids):06d}"
                EYE_FRAMES[fid] = eye_frame(tag, i, n, defect)
                out.append({"frameId": fid, "frameUrl": f"/api/eye/frames/{fid}.jpg", "actor": actor,
                            "camera": {"position": [0, 1, 2], "target": [0, 0, 0], "fov": 60},
                            "visiblePins": [{"assetTag": tag, "x": 0.5, "y": 0.5, "distance": 1.2, "occluded": False}],
                            "defect": defect, "at": "2026-10-17T00:00:00Z"})
            return self._send(200, out)
        if u.path == "/v1/messages":
            return self._send(200, anthropic_reply(body))
        self._send(404, {"detail": "not found"})


def serve(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    srv = serve(ap.parse_args().port)
    print("READY", srv.server_address[1], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    sys.exit(0)
