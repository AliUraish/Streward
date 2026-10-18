/**
 * show_factory's MCP Apps view (REALITY-CONTRACT-3.md §10). A self-contained page: no build step, no React. It is
 * registered through mcp-use's views registry as an inline entry, so mcp-use synthesises the HTML document, serves
 * it as `ui://views/steward-factory.html` (mime `text/html;profile=mcp-app`) and puts `_meta.ui.resourceUri` on the
 * tool. The page:
 *
 *  - talks to the host over the MCP Apps postMessage bridge (ui/initialize, ui/notifications/tool-result) and also
 *    reads the ChatGPT Apps SDK globals (window.openai.toolOutput), so one page serves Claude and ChatGPT;
 *  - loads the PlayCanvas engine from a pinned CDN URL and renders the site's SOG scan straight from the CloudFront
 *    meta.json (never rehosted), in black and white (grayscale canvas, white ink);
 *  - projects every asset's 3-D pin into a DOM dot each frame (hidden behind the camera), sized by issue severity,
 *    dashed when the pin is estimated; hover shows the issue card; click focuses the camera and asks the host to
 *    call focus_view so the dashboard viewer follows;
 *  - always shows the issue list and the credit line, so a client without WebGL or CDN access still gets the facts.
 *
 * The widget JS is a plain string (no template placeholders) so it can be embedded as is.
 */
import type { z } from 'zod';
import type { SceneSchema } from './schemas3.js';

export const PLAYCANVAS_VERSION = '2.23.3';
export const PLAYCANVAS_URL = `https://cdn.jsdelivr.net/npm/playcanvas@${PLAYCANVAS_VERSION}/build/playcanvas.min.mjs`;
export const FACTORY_VIEW = 'steward-factory';
export const FACTORY_VIEW_URI = `ui://views/${FACTORY_VIEW}.html`;
/** Hosts build the iframe CSP from these: the engine CDN, the CloudFront scan origin, the SuperSplat thumbnails. */
export const FACTORY_VIEW_CSP = {
  resourceDomains: ['https://cdn.jsdelivr.net', 'https://d28zzqy0iyovbz.cloudfront.net', 'https://s3-eu-west-1.amazonaws.com'],
  connectDomains: ['https://cdn.jsdelivr.net', 'https://d28zzqy0iyovbz.cloudfront.net'],
};

export const FACTORY_VIEW_CSS = String.raw`
:root{color-scheme:dark}
html,body{margin:0;background:#000;color:#fff;font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
#root{background:#000}
.sw{display:flex;flex-direction:column;gap:10px;padding:12px}
.sw header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.sw header b{font-size:15px;font-weight:600;letter-spacing:-.01em}
.sw header span{color:#9a9a9a;margin-left:8px}
.legend{display:flex;gap:12px;color:#9a9a9a;font-size:12px;align-items:center}
.legend i{display:inline-block;border-radius:50%;background:#fff;margin-right:5px;vertical-align:middle}
.stage{position:relative;height:420px;background:#0b0b0b;border-radius:10px;overflow:hidden}
.stage canvas{position:absolute;inset:0;width:100%;height:100%;filter:grayscale(1) contrast(1.05)}
#dots{position:absolute;inset:0;pointer-events:none}
.dot{position:absolute;transform:translate(-50%,-50%);border-radius:50%;background:#fff;box-shadow:0 0 0 2px #000;pointer-events:auto;cursor:pointer}
.dot.none{background:#7a7a7a;width:6px;height:6px}
.dot.low{width:9px;height:9px}
.dot.medium{width:12px;height:12px}
.dot.high{width:16px;height:16px;box-shadow:0 0 0 2px #000,0 0 0 4px #fff}
.dot.estimated{background:transparent;border:1.5px dashed #fff}
.dot.none.estimated{border-color:#7a7a7a}
#card{position:absolute;max-width:260px;background:#111;border-radius:8px;padding:9px 11px;pointer-events:none;font-size:12px;z-index:3}
#card .tag{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
#card p{margin:4px 0 0;color:#cfcfcf}
#status{position:absolute;left:12px;bottom:10px;right:12px;color:#bdbdbd;font-size:12px}
ol{list-style:none;margin:0;padding:0;display:grid;gap:4px}
li{display:grid;grid-template-columns:70px 1fr auto;gap:10px;padding:6px 8px;background:#0d0d0d;border-radius:6px;cursor:pointer}
li .tag{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
li .sev{color:#9a9a9a}
li.high .sev{color:#fff;font-weight:600}
footer{color:#8a8a8a;font-size:11.5px}
footer a{color:#cfcfcf}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
`;

export const FACTORY_VIEW_JS = String.raw`
var PLAYCANVAS_URL = "__PLAYCANVAS_URL__";
var root = document.getElementById("root");
root.removeAttribute("data-mcp-use-loading");
root.innerHTML = '<div class="sw"><header><div><b id="title">Steward</b><span id="sub">waiting for the tool result</span></div>' +
  '<div class="legend"><span><i style="width:16px;height:16px"></i>high</span><span><i style="width:12px;height:12px"></i>medium</span><span><i style="width:9px;height:9px"></i>low</span><span><i style="width:9px;height:9px;background:transparent;border:1.5px dashed #fff"></i>pin estimated</span></div></header>' +
  '<div class="stage" id="stage"><canvas id="c"></canvas><div id="dots"></div><div id="card" hidden></div><div id="status"></div></div>' +
  '<ol id="list"></ol><footer id="credit"></footer></div>';
var $ = function (id) { return document.getElementById(id); };
var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
var status = function (text) { $("status").textContent = text || ""; };

/* ---- host bridge: MCP Apps (postMessage JSON-RPC) and ChatGPT Apps SDK globals ---- */
var nextId = 1, pending = {};
function post(msg) { try { window.parent.postMessage(msg, "*"); } catch (e) { /* no host */ } }
function request(method, params) {
  var id = nextId++;
  post({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
  return new Promise(function (resolve, reject) {
    pending[id] = { resolve: resolve, reject: reject };
    setTimeout(function () { if (pending[id]) { delete pending[id]; reject(new Error("timeout " + method)); } }, 10000);
  });
}
function notify(method, params) { post({ jsonrpc: "2.0", method: method, params: params || {} }); }
window.addEventListener("message", function (e) {
  var m = e.data;
  if (!m || typeof m !== "object" || m.jsonrpc !== "2.0") return;
  if (m.id !== undefined && m.method === undefined) {
    var p = pending[m.id]; if (!p) return; delete pending[m.id];
    if (m.error) p.reject(new Error(m.error.message || "error")); else p.resolve(m.result);
    return;
  }
  if (m.method === "ui/notifications/tool-result" && m.params) onResult(m.params);
  if (m.method === "ui/notifications/tool-input" && m.params && m.params.arguments && m.params.arguments.siteId) siteArg = m.params.arguments.siteId;
  if (m.id !== undefined && m.method) post({ jsonrpc: "2.0", id: m.id, result: {} });
});
var siteArg = null;
function onResult(result) { var data = result && (result.structuredContent || null); if (data && data.siteId && data.assets) render(data); }
request("ui/initialize", { appInfo: { name: "steward-factory", version: "1.0.0" }, appCapabilities: {}, protocolVersion: "2026-01-26" })
  .then(function () { notify("ui/notifications/initialized", {}); }).catch(function () { /* not an MCP Apps host */ });
function fromOpenAI() { var o = window.openai; if (o && o.toolOutput && o.toolOutput.siteId) render(o.toolOutput); }
window.addEventListener("openai:set_globals", fromOpenAI);
setTimeout(fromOpenAI, 0);
if (window.__STEWARD_SCENE__) setTimeout(function () { render(window.__STEWARD_SCENE__); }, 0);
function openLink(url) { request("ui/open-link", { url: url }).catch(function () { try { window.open(url, "_blank", "noopener"); } catch (e) { /* blocked */ } }); }

/* ---- page ---- */
var scene = null, started = false, view = null;
var RANK = { high: 3, medium: 2, low: 1, none: 0 };
function render(data) {
  scene = data;
  $("title").textContent = data.name;
  $("sub").textContent = data.counts.openIssues + " open issue" + (data.counts.openIssues === 1 ? "" : "s") + " · " + data.counts.assets + " assets · " + data.counts.estimated + " pins estimated";
  var c = data.credit || {};
  $("credit").innerHTML = esc(c.scene) + " · " + esc(c.author) + ' · <a href="' + esc(c.url) + '" id="creditlink">' + esc(String(c.url || "").replace(/^https?:\/\//, "")) + "</a>" +
    " · third-party capture, loaded from its hosted origin. Synthetic issues are labelled in the record.";
  var link = $("creditlink"); if (link) link.addEventListener("click", function (e) { e.preventDefault(); openLink(c.url); });
  var rows = data.assets.slice().sort(function (a, b) { return (RANK[b.severity] - RANK[a.severity]) || (b.issues.length - a.issues.length) || a.assetTag.localeCompare(b.assetTag); });
  $("list").innerHTML = rows.filter(function (a) { return a.issues.length; }).map(function (a) {
    return '<li class="' + a.severity + '" data-tag="' + esc(a.assetTag) + '"><span class="tag">' + esc(a.assetTag) + "</span><span>" + esc(a.name) + " · " +
      a.issues.map(function (i) { return esc(i.summary); }).join("; ") + '</span><span class="sev">' + a.severity + "</span></li>";
  }).join("") || '<li class="none"><span class="tag">—</span><span>No open issues on this site.</span><span class="sev"></span></li>';
  Array.prototype.forEach.call(document.querySelectorAll("li[data-tag]"), function (li) { li.addEventListener("click", function () { focusAsset(li.getAttribute("data-tag")); }); });
  buildDots();
  if (!started) { started = true; start3d(data); }
  notify("ui/notifications/size-changed", { height: document.documentElement.scrollHeight });
}
var dotEls = {};
function buildDots() {
  var host = $("dots"); host.innerHTML = ""; dotEls = {};
  scene.assets.forEach(function (a) {
    if (!a.pin) return;
    var d = document.createElement("div");
    d.className = "dot " + a.severity + (a.pinSource === "placed" ? "" : " estimated");
    d.style.display = "none";
    d.addEventListener("mouseenter", function () { showCard(a, d); });
    d.addEventListener("mouseleave", function () { $("card").hidden = true; });
    d.addEventListener("click", function () { focusAsset(a.assetTag); });
    host.appendChild(d); dotEls[a.assetTag] = d;
  });
}
function showCard(a, d) {
  var card = $("card");
  card.innerHTML = '<span class="tag">' + esc(a.assetTag) + "</span> " + esc(a.name) + " <span style=\"color:#9a9a9a\">(" + esc(a.kind) + ")</span>" +
    (a.issues.length ? a.issues.map(function (i) { return "<p>" + esc(i.severity) + ": " + esc(i.summary) + "</p>"; }).join("") : "<p>No open issues.</p>") +
    (a.pinSource === "placed" ? "" : "<p>Pin position estimated, not placed on the scan.</p>");
  card.style.left = Math.min(parseFloat(d.style.left) + 14, $("stage").clientWidth - 270) + "px";
  card.style.top = Math.max(parseFloat(d.style.top) - 10, 6) + "px";
  card.hidden = false;
}
function focusAsset(tag) {
  var a = scene && scene.assets.filter(function (x) { return x.assetTag === tag; })[0];
  if (view && a && a.pin) view.focus(a.pin);
  request("tools/call", { name: "focus_view", arguments: { siteId: scene.siteId, assetTag: tag, action: "focus" } }).catch(function () { /* host may not allow app tool calls */ });
}

/* ---- 3-D: PlayCanvas engine, SOG gsplat asset, projected DOM dots ---- */
function start3d(data) {
  var probe = document.createElement("canvas");
  if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) { status("WebGL is not available in this client; the list below is the full summary."); return; }
  status("Loading the 3-D engine…");
  import(PLAYCANVAS_URL).then(function (pc) { boot(pc, data); }).catch(function () {
    status("The 3-D engine could not load in this client (CDN blocked); the list below is the full summary.");
  });
}
function boot(pc, data) {
  var canvas = $("c"), stage = $("stage");
  var app = new pc.Application(canvas, { mouse: new pc.Mouse(canvas), touch: new pc.TouchDevice(canvas), graphicsDeviceOptions: { antialias: false, alpha: false } });
  app.setCanvasFillMode(pc.FILLMODE_NONE);
  app.setCanvasResolution(pc.RESOLUTION_AUTO);
  function resize() { app.resizeCanvas(stage.clientWidth, stage.clientHeight); }
  if (window.ResizeObserver) new ResizeObserver(resize).observe(stage);
  resize();
  app.start();
  var preset = data.cameraPresets && data.cameraPresets[0];
  var cam = new pc.Entity("camera");
  cam.addComponent("camera", { clearColor: new pc.Color(0, 0, 0, 1), fov: Math.min(90, (preset && preset.fov) || 60), nearClip: 0.02, farClip: 1000 });
  app.root.addChild(cam);
  var pins = data.assets.filter(function (a) { return a.pin; }).map(function (a) { return a.pin; });
  var center = pins.length ? pins.reduce(function (s, p) { return { x: s.x + p.x / pins.length, y: s.y + p.y / pins.length, z: s.z + p.z / pins.length }; }, { x: 0, y: 0, z: 0 }) : { x: 0, y: 0, z: 0 };
  var pos = preset ? new pc.Vec3(preset.position[0], preset.position[1], preset.position[2]) : new pc.Vec3(center.x, center.y + 1.5, center.z + 4);
  var target = preset ? new pc.Vec3(preset.target[0], preset.target[1], preset.target[2]) : new pc.Vec3(center.x, center.y, center.z);
  var dir = new pc.Vec3().sub2(target, pos);
  var dist = dir.length();
  if (dist > 12 || dist < 0.05) { dir.normalize().mulScalar(3); target = new pc.Vec3().add2(pos, dir); dist = 3; }
  var offset = new pc.Vec3().sub2(pos, target);
  var yaw = Math.atan2(offset.x, offset.z), pitch = Math.asin(Math.max(-1, Math.min(1, offset.y / dist)));
  var home = { yaw: yaw, pitch: pitch, dist: dist, target: target.clone() };
  var goal = null;
  function place() {
    var cp = Math.cos(pitch);
    cam.setPosition(target.x + dist * Math.sin(yaw) * cp, target.y + dist * Math.sin(pitch), target.z + dist * Math.cos(yaw) * cp);
    cam.lookAt(target);
  }
  place();
  var drag = null;
  canvas.addEventListener("pointerdown", function (e) { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", function (e) {
    if (!drag) return;
    yaw -= (e.clientX - drag.x) * 0.006; pitch = Math.max(-1.45, Math.min(1.45, pitch + (e.clientY - drag.y) * 0.006));
    drag = { x: e.clientX, y: e.clientY }; goal = null; place();
  });
  canvas.addEventListener("pointerup", function () { drag = null; });
  canvas.addEventListener("wheel", function (e) { e.preventDefault(); dist = Math.max(0.3, Math.min(40, dist * (1 + Math.sign(e.deltaY) * 0.1))); goal = null; place(); }, { passive: false });
  canvas.addEventListener("dblclick", function () { goal = { target: home.target.clone(), dist: home.dist }; yaw = home.yaw; pitch = home.pitch; });
  view = { focus: function (p) { goal = { target: new pc.Vec3(p.x, p.y, p.z), dist: Math.min(dist, 1.8) }; } };
  var asset = new pc.Asset("scan", "gsplat", { url: data.sogUrl });
  asset.on("load", function () {
    var entity = new pc.Entity("scan");
    entity.addComponent("gsplat", { asset: asset });
    app.root.addChild(entity);
    status("");
  });
  asset.on("error", function (err) { status("The scan could not be loaded (" + err + "); the list below is the full summary."); });
  app.assets.add(asset);
  app.assets.load(asset);
  status("Loading " + data.gaussians + " gaussians from the hosted capture…");
  var screen = new pc.Vec3(), world = new pc.Vec3(), toPin = new pc.Vec3();
  app.on("update", function () {
    if (goal) {
      target.lerp(target, goal.target, 0.12); dist += (goal.dist - dist) * 0.12;
      if (target.distance(goal.target) < 0.005 && Math.abs(goal.dist - dist) < 0.005) goal = null;
      place();
    }
    var camPos = cam.getPosition(), fwd = cam.forward;
    scene.assets.forEach(function (a) {
      var d = dotEls[a.assetTag]; if (!d || !a.pin) return;
      world.set(a.pin.x, a.pin.y, a.pin.z);
      toPin.sub2(world, camPos);
      if (toPin.dot(fwd) <= 0.05) { d.style.display = "none"; return; }
      cam.camera.worldToScreen(world, screen);
      if (screen.x < -20 || screen.y < -20 || screen.x > stage.clientWidth + 20 || screen.y > stage.clientHeight + 20) { d.style.display = "none"; return; }
      d.style.display = "block"; d.style.left = screen.x + "px"; d.style.top = screen.y + "px";
    });
  });
}
`.replace('__PLAYCANVAS_URL__', PLAYCANVAS_URL);

type Scene = z.infer<typeof SceneSchema>;

/** The text fallback every client gets (the widget is extra). Compact: one line per asset with open issues. */
export function factorySummary(scene: Scene): string {
  const rank: Record<string, number> = { high: 3, medium: 2, low: 1, none: 0 };
  const lines = scene.assets.filter(asset => asset.issues.length)
    .sort((a, b) => (rank[b.severity]! - rank[a.severity]!) || a.assetTag.localeCompare(b.assetTag))
    .slice(0, 20)
    .map(asset => `- ${asset.severity.toUpperCase()} ${asset.assetTag} ${asset.name}: ${asset.issues.map(issue => `${issue.summary} (${issue.id}, ${issue.status})`).join('; ')}${asset.pinSource === 'placed' ? '' : ' [pin estimated]'}`);
  return [
    `${scene.name} (${scene.siteId}): ${scene.counts.assets} assets, ${scene.counts.openIssues} open issue${scene.counts.openIssues === 1 ? '' : 's'}; pins ${scene.counts.pinned} (${scene.counts.estimated} estimated).`,
    ...(lines.length ? lines : ['- No open issues.']),
    `Scan: ${scene.credit.text}. Loaded at runtime from ${scene.sogUrl}; never rehosted.`,
    'Clients with MCP Apps support render this as an interactive 3-D view (black and white, issue dots on the scan); this text is the same content for every other client.',
  ].join('\n');
}
