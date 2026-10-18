"use client";

/* The plant elevation, with continuous volumetric gas inside the equipment. The workflow stays in the gauge,
   labels and verification ticks; no travelling ball or orbiting marker competes with the flow. */
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import * as THREE from "three";
import { EDGE_X, GAUGE, PIPE_Y, START, TOTAL, WORLD_CY, WORLD_H, WORLD_W, X, clamp01, ease, lerp, loopP, type V2 } from "./story";
import { CROSS_AT, Draw, NEEDLE_LEN, TICKS, WHEEL_Y, barAngle, buildStatic, cross, tick, toArray, wheel } from "./hero-sketch";
import HeroGas from "./hero-gas";

export interface HeroControl { nudge: number | null; visible: boolean }
interface Props { control: MutableRefObject<HeroControl>; attestationId: string; still?: boolean; onProgress?: (p: number) => void }
type LabelMap = Record<string, HTMLElement | null>;

const WHITE = "#ffffff";
const LABELS: Record<string, V2> = { agent: [EDGE_X + 0.25, PIPE_Y + 0.55], p101: [X.p101, -1.95], p102: [X.p102, -1.95], gauge: [GAUGE[0] - 0.95, GAUGE[1]], tank: [X.tank, -2.55], v501: [X.v501, WHEEL_Y + 0.6], v504: [X.v504, WHEEL_Y + 0.6] };
const ANCHOR: Record<string, string> = { agent: "0, -50%", gauge: "-100%, -50%" };

function geo(arr: Float32Array) { const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(arr, 3)); return g; }
function mat(opacity = 1) { return new THREE.LineBasicMaterial({ color: WHITE, transparent: true, opacity }); }
function segsOf(fn: (d: Draw) => void) { const d = new Draw(); fn(d); return toArray(d.segs); }
function Part({ obj }: { obj: THREE.Object3D }) { return <primitive object={obj} />; }

function Drawing({ control, still, labels, onBeat, onProgress }: Props & { labels: MutableRefObject<LabelMap>; onBeat: (b: number) => void }) {
  const { camera, size } = useThree();
  const offset = useRef(0); const lastP = useRef(-1); const beatRef = useRef(-1);
  const proj = useMemo(() => new THREE.Vector3(), []);

  const base = useMemo(() => new THREE.LineSegments(geo(toArray(buildStatic())), mat(0.82)), []);
  const wheels = useMemo(() => [X.v501, X.v504].map(x => { const o = new THREE.LineSegments(geo(segsOf(d => wheel(d))), mat(0.82)); o.position.set(x, WHEEL_Y, 0); return o; }), []);
  const needleObj = useMemo(() => { const o = new THREE.LineSegments(geo(new Float32Array([-0.08, 0, 0, NEEDLE_LEN, 0, 0])), mat(1)); o.position.set(GAUGE[0], GAUGE[1], 0.01); return o; }, []);
  const crossObj = useMemo(() => { const o = new THREE.LineSegments(geo(segsOf(d => cross(d, [0, 0]))), mat(1)); o.position.set(CROSS_AT[0], CROSS_AT[1], 0); o.visible = false; return o; }, []);
  const ticks = useMemo(() => TICKS.map(c => { const o = new THREE.LineSegments(geo(segsOf(d => tick(d, [0, 0]))), mat(1)); o.position.set(c[0], c[1], 0); o.visible = false; return o; }), []);

  /* Fit the drawing to the canvas. */
  useEffect(() => {
    const cam = camera as THREE.OrthographicCamera;
    cam.zoom = Math.min(size.width / WORLD_W, size.height / WORLD_H);
    cam.position.set(0, WORLD_CY, 10); cam.lookAt(0, WORLD_CY, 0); cam.updateProjectionMatrix();
  }, [camera, size]);
  useEffect(() => () => {
    for (const object of [base, ...wheels, needleObj, crossObj, ...ticks]) {
      object.geometry.dispose();
      (object.material as THREE.Material).dispose();
    }
  }, [base, wheels, needleObj, crossObj, ticks]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const c = control.current;
    let p: number; let lt = TOTAL;
    if (still) p = 5;
    else {
      if (c.nudge !== null) { offset.current = t - START[c.nudge]; c.nudge = null; }
      lt = (((t - offset.current) % TOTAL) + TOTAL) % TOTAL;
      p = loopP(lt);
    }
    const b = Math.min(4, Math.floor(p)); const f = p >= 5 ? 1 : p - b;
    const nextBeat = p >= 5 ? 5 : b;
    if (nextBeat !== beatRef.current) { beatRef.current = nextBeat; onBeat(nextBeat); }
    if (onProgress && Math.abs(p - lastP.current) > 0.004) { lastP.current = p; onProgress(p); }

    /* A slow drift of the camera, a fraction of a unit. */
    if (!still) { camera.position.x = Math.sin(t * 0.07) * 0.18; camera.position.y = WORLD_CY + Math.sin(t * 0.05) * 0.06; }

    /* Slow mechanical motion stays behind the gas. */
    wheels.forEach((w, i) => { w.rotation.z = still ? 0 : t * 0.12 * (i ? -1 : 1); });

    /* The needle: rests low, settles on 2.4 bar during the proof, eases back during the rest. */
    let bar = 0.4;
    if (p >= 1 && p < 2) bar = lerp(0.4, 2.4, ease(f / 0.6));
    else if (p >= 2 && p < 5) bar = 2.4;
    else if (p >= 5) bar = still ? 2.4 : lerp(2.4, 0.4, ease((lt - START[4] - 2.8) / 1.6));
    needleObj.rotation.z = barAngle(bar);

    /* The refusal and the six ticks. */
    crossObj.visible = p >= 3.1 && p < 4.6; const cs = p < 3.1 ? 0 : clamp01((p - 3.1) / 0.15); crossObj.scale.set(cs, cs, 1);
    ticks.forEach((tk, i) => { const s0 = 0.62 + i * 0.06; const s = p < 3 ? 0 : p < 4 ? ease((f - s0) / 0.08) : 1; tk.visible = s > 0.01; tk.scale.set(s, s, 1); });

    const narrow = size.width < 640;
    for (const key of Object.keys(LABELS)) {
      const el = labels.current[key]; if (!el) continue;
      let [x, y] = LABELS[key]; let anchor = ANCHOR[key] ?? "-50%, -50%";
      if (narrow && key === "p101") { x = X.p101 - 1.6; anchor = "0, -50%"; }   /* on a phone the citation would run off the left edge */
      proj.set(x, y, 0).project(camera);
      el.style.transform = `translate(${anchor}) translate(${((proj.x + 1) / 2) * size.width}px, ${((1 - proj.y) / 2) * size.height}px)`;
    }
  });

  return <>
    <HeroGas still={still} />
    <Part obj={base} />
    {wheels.map((w, i) => <Part key={i} obj={w} />)}
    <Part obj={needleObj} /><Part obj={crossObj} />
    {ticks.map((tk, i) => <Part key={`t${i}`} obj={tk} />)}
  </>;
}

export default function HeroScene({ control, attestationId, still, onProgress }: Props) {
  const [frameloop, setFrameloop] = useState<"always" | "demand">("always");
  const labels = useRef<LabelMap>({});
  const [beat, setBeat] = useState(0);
  const bind = (key: string) => (el: HTMLElement | null) => { labels.current[key] = el; };
  useEffect(() => {
    if (still) { setFrameloop("demand"); return; }
    let raf = 0;
    const tick = () => { setFrameloop(control.current.visible ? "always" : "demand"); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [control, still]);
  const shown = still ? 4 : beat;
  return <>
  <Canvas orthographic frameloop={frameloop} dpr={[1, 1.5]} gl={{ antialias: true, alpha: false, powerPreference: "low-power" }} camera={{ position: [0, WORLD_CY, 10], near: 0.1, far: 50, zoom: 60 }} onCreated={({ gl }) => { gl.setClearColor("#000000", 1); }} style={{ position: "absolute", inset: 0 }}>
    <Drawing control={control} attestationId={attestationId} still={still} onProgress={onProgress} labels={labels} onBeat={setBeat} />
  </Canvas>
  <div className="labels" aria-hidden="true">
    <div ref={bind("agent")} className={`lbl ${shown === 0 || shown >= 4 ? "on" : "dim"}`}><span className="tag">agent</span>{shown === 0 ? <span>resolve(harbor-works, P-101)</span> : shown >= 4 ? <span>{attestationId}</span> : null}</div>
    <div ref={bind("p101")} className={`lbl ${shown >= 1 ? "on" : "dim"}`}><span className="tag">P-101</span>{shown === 1 ? <span>known · CC-2026-0611-P101</span> : shown >= 3 ? <span>2.4 bar · accepted</span> : null}</div>
    <div ref={bind("p102")} className={`lbl ${shown === 2 || shown === 3 ? "on" : "dim"}`}><span className="tag">P-102</span>{shown === 3 ? <span>wrong plate</span> : null}</div>
    <div ref={bind("gauge")} className="lbl dim"><span className="tag">PG-601</span></div>
    <div ref={bind("tank")} className="lbl dim"><span className="tag">TK-201</span></div>
    <div ref={bind("v501")} className="lbl dim"><span className="tag">V-501</span></div>
    <div ref={bind("v504")} className="lbl dim"><span className="tag">V-504</span></div>
  </div>
  </>;
}
