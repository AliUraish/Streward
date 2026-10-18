'use client';

import React, { Component as ReactComponent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { ArrowUpRight, Camera, ArrowsOut as Expand, Crosshair as Focus, CrosshairSimple as LocateFixed, ArrowsOutCardinal as Move, ArrowCounterClockwise as RotateCcw, Scan as ScanLine } from '@phosphor-icons/react';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import type { Component, Vec3 } from '../../../../shared/types';
import { MARKER_HEIGHT, SceneLighting, SceneWorld } from './world';
import styles from './scene.module.css';

export interface PlantRoomProps {
  components: Component[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  showMarkers?: boolean;
  showGuides?: boolean;
  viewMode?: 'orbit' | 'walk';
  cameraTarget?: string | null;
  /** Hide helpers when a parent workspace supplies its own navigation chrome. */
  showControls?: boolean;
}

interface SceneBoundaryProps { children: React.ReactNode; }
class SceneBoundary extends ReactComponent<SceneBoundaryProps, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(error: Error) { return { error: error.message }; }
  render() {
    if (this.state.error) return <div className={styles.fallback}><Camera size={26} /><strong>3D view unavailable</strong><span>{this.state.error}</span><button type="button" onClick={() => this.setState({ error: null })}>Try again</button></div>;
    return this.props.children;
  }
}

const INITIAL_POSITION: Vec3 = [5.6, 2.85, 5.35];
const INITIAL_TARGET: Vec3 = [-.7, 1.6, -1.45];
const targetHeight: Record<string, number> = { pump: 1, tank: 1.5, exchanger: 1.2, panel: .5, valve: .02, duct: .02, fire: .4, door: 1.3 };

function CameraRig({ mode, targetId, components, resetKey }: {
  mode: 'orbit' | 'walk'; targetId: string | null; components: Component[]; resetKey: number;
}) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera, gl, invalidate } = useThree();
  const movement = useRef(new Set<string>());
  const targetPosition = useRef(new THREE.Vector3(...INITIAL_POSITION));
  const targetLookAt = useRef(new THREE.Vector3(...INITIAL_TARGET));
  const isTransitioning = useRef(true);
  const dragging = useRef(false);
  const euler = useMemo(() => new THREE.Euler(0, 0, 0, 'YXZ'), []);
  const forward = useMemo(() => new THREE.Vector3(), []);
  const sideways = useMemo(() => new THREE.Vector3(), []);
  const move = useMemo(() => new THREE.Vector3(), []);

  useEffect(() => {
    targetPosition.current.set(...INITIAL_POSITION);
    targetLookAt.current.set(...INITIAL_TARGET);
    isTransitioning.current = true;
    invalidate();
  }, [resetKey, invalidate]);

  // Focus requests are explicit. Selecting a world marker does not unexpectedly move the camera.
  useEffect(() => {
    if (targetId?.startsWith('reset-')) {
      targetPosition.current.set(...INITIAL_POSITION);
      targetLookAt.current.set(...INITIAL_TARGET);
      isTransitioning.current = true;
      invalidate();
      return;
    }
    const component = components.find(item => item.id === targetId);
    if (!component) return;
    const [x, y, z] = component.position;
    targetLookAt.current.set(x, y + (targetHeight[component.kind] ?? .25), z);
    const offset = component.kind === 'duct' ? new THREE.Vector3(1.4, -.9, 2.8) : new THREE.Vector3(2, 1.15, 3.2);
    targetPosition.current.copy(targetLookAt.current).add(offset);
    targetPosition.current.x = THREE.MathUtils.clamp(targetPosition.current.x, -6.15, 6.15);
    targetPosition.current.y = THREE.MathUtils.clamp(targetPosition.current.y, .5, 4.3);
    targetPosition.current.z = THREE.MathUtils.clamp(targetPosition.current.z, -5.6, 5.6);
    isTransitioning.current = true;
    invalidate();
  // Component positions are the stable shared scene contract; polling status changes need not refocus.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId, invalidate]);

  useEffect(() => {
    const element = gl.domElement;
    element.tabIndex = 0;
    element.setAttribute('aria-label', 'Interactive plant room. Drag to look, scroll to zoom. In walk mode use W A S D or arrow keys.');
    const focus = () => element.focus({ preventScroll: true });
    const down = (event: KeyboardEvent) => {
      if (mode !== 'walk' || document.activeElement !== element) return;
      if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'].includes(event.code)) {
        event.preventDefault(); movement.current.add(event.code); isTransitioning.current = false; invalidate();
      }
    };
    const up = (event: KeyboardEvent) => movement.current.delete(event.code);
    const blur = () => { movement.current.clear(); dragging.current = false; };
    const pointerDown = (event: PointerEvent) => {
      focus();
      if (mode === 'walk' && event.button === 0) {
        dragging.current = true; element.setPointerCapture(event.pointerId);
        isTransitioning.current = false;
      }
    };
    const pointerUp = () => { dragging.current = false; };
    const pointerMove = (event: PointerEvent) => {
      if (mode !== 'walk' || !dragging.current) return;
      euler.setFromQuaternion(camera.quaternion);
      euler.y -= event.movementX * .003;
      euler.x = THREE.MathUtils.clamp(euler.x - event.movementY * .003, -1.45, 1.45);
      euler.z = 0;
      camera.quaternion.setFromEuler(euler);
      invalidate();
    };
    window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', blur);
    element.addEventListener('pointerdown', pointerDown); element.addEventListener('pointerup', pointerUp); element.addEventListener('pointercancel', pointerUp); element.addEventListener('pointermove', pointerMove);
    return () => {
      movement.current.clear();
      window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur);
      element.removeEventListener('pointerdown', pointerDown); element.removeEventListener('pointerup', pointerUp); element.removeEventListener('pointercancel', pointerUp); element.removeEventListener('pointermove', pointerMove);
    };
  }, [camera, euler, gl, invalidate, mode]);

  useEffect(() => {
    if (mode === 'orbit' && controls.current) {
      camera.getWorldDirection(forward);
      controls.current.target.copy(camera.position).addScaledVector(forward, 5);
      controls.current.update();
    }
  }, [mode, camera, forward]);

  useFrame((_, delta) => {
    if (isTransitioning.current) {
      const alpha = 1 - Math.exp(-delta * 5.5);
      camera.position.lerp(targetPosition.current, alpha);
      if (mode === 'orbit' && controls.current) {
        controls.current.target.lerp(targetLookAt.current, alpha); controls.current.update();
      } else camera.lookAt(targetLookAt.current);
      if (camera.position.distanceTo(targetPosition.current) < .006) isTransitioning.current = false;
      invalidate();
    }
    if (mode !== 'walk' || movement.current.size === 0) return;
    camera.getWorldDirection(forward); forward.y = 0; forward.normalize();
    sideways.crossVectors(forward, camera.up).normalize();
    move.set(0, 0, 0);
    const keys = movement.current;
    if (keys.has('KeyW') || keys.has('ArrowUp')) move.add(forward);
    if (keys.has('KeyS') || keys.has('ArrowDown')) move.sub(forward);
    if (keys.has('KeyD') || keys.has('ArrowRight')) move.add(sideways);
    if (keys.has('KeyA') || keys.has('ArrowLeft')) move.sub(sideways);
    if (keys.has('KeyE')) move.y += 1;
    if (keys.has('KeyQ')) move.y -= 1;
    if (move.lengthSq() > 0) {
      camera.position.addScaledVector(move.normalize(), Math.min(delta, .05) * (keys.has('ShiftLeft') || keys.has('ShiftRight') ? 5 : 2));
      camera.position.x = THREE.MathUtils.clamp(camera.position.x, -6.15, 6.15);
      camera.position.y = THREE.MathUtils.clamp(camera.position.y, .45, 4.2);
      camera.position.z = THREE.MathUtils.clamp(camera.position.z, -5.6, 5.7);
      invalidate();
    }
  });

  return mode === 'orbit' ? <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={.12} target={INITIAL_TARGET} minDistance={.6} maxDistance={20} maxPolarAngle={Math.PI * .94} onStart={() => { isTransitioning.current = false; }} /> : null;
}

// The DOM overlay belongs to the main React root. Drei Html creates independent
// roots per marker whose synchronous cleanup races React 19/Strict Mode unmounts.
// This bridge only projects world coordinates into existing, normal DOM elements.
function OverlayProjection({ components, markers, compass, refreshKey }: {
  components: Component[];
  markers: React.RefObject<Map<string, HTMLDivElement>>;
  compass: React.RefObject<HTMLDivElement | null>;
  refreshKey: string;
}) {
  const { camera, size, invalidate } = useThree();
  const projected = useMemo(() => new THREE.Vector3(), []);
  const direction = useMemo(() => new THREE.Vector3(), []);
  const anchors = useMemo(() => components.map(component => {
    const offset = new THREE.Vector3(0, MARKER_HEIGHT[component.kind] ?? .5, component.kind === 'panel' ? .35 : .2);
    if (component.rotation) offset.applyEuler(new THREE.Euler(...component.rotation));
    return { id: component.id, position: offset.add(new THREE.Vector3(...component.position)) };
  }), [components]);
  const lastBearing = useRef<number | null>(null);
  useEffect(() => { invalidate(); }, [invalidate, refreshKey, anchors]);
  useFrame(() => {
    camera.updateMatrixWorld();
    for (const anchor of anchors) {
      const element = markers.current.get(anchor.id);
      if (!element) continue;
      projected.copy(anchor.position).project(camera);
      const visible = projected.z > -1 && projected.z < 1 && Math.abs(projected.x) < 1.15 && Math.abs(projected.y) < 1.15;
      element.style.visibility = visible ? 'visible' : 'hidden';
      if (!visible) continue;
      const distance = camera.position.distanceTo(anchor.position);
      const fov = (camera as THREE.PerspectiveCamera).fov || 58;
      const scale = THREE.MathUtils.clamp(11 / (2 * Math.tan(THREE.MathUtils.degToRad(fov) / 2) * distance), .65, 1.65);
      const x = (projected.x + 1) * size.width / 2;
      const y = (1 - projected.y) * size.height / 2;
      element.style.transform = `translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,0) scale(${scale.toFixed(3)})`;
      element.style.zIndex = String(Math.max(1, 25 - Math.round(distance)));
    }
    if (compass.current) {
      camera.getWorldDirection(direction);
      const bearing = Math.round(THREE.MathUtils.radToDeg(Math.atan2(direction.x, -direction.z)));
      if (bearing !== lastBearing.current) {
        lastBearing.current = bearing;
        const label = compass.current.firstElementChild as HTMLElement;
        const value = compass.current.lastElementChild as HTMLElement;
        if (label) label.style.transform = `rotate(${-bearing}deg)`;
        if (value) value.textContent = `${((bearing + 360) % 360).toString().padStart(3, '0')}°`;
      }
    }
  });
  return null;
}

export function PlantRoom({ components, selectedId, onSelect, showMarkers = true, showGuides = false, viewMode = 'orbit', cameraTarget = null, showControls = true }: PlantRoomProps) {
  const [resetKey, setResetKey] = useState(0);
  const [mode, setMode] = useState(viewMode);
  const [focused, setFocused] = useState<string | null>(cameraTarget);
  const container = useRef<HTMLDivElement>(null);
  const markerElements = useRef(new Map<string, HTMLDivElement>());
  const compass = useRef<HTMLDivElement>(null);
  useEffect(() => setMode(viewMode), [viewMode]);
  useEffect(() => setFocused(cameraTarget), [cameraTarget]);
  const reset = () => { setFocused(null); setResetKey(value => value + 1); };
  return <div className={styles.plantRoom} ref={container} data-testid="plant-room">
    <SceneBoundary>
      <Canvas shadows frameloop="demand" dpr={[1, 1.5]} camera={{ position: INITIAL_POSITION, fov: 58, near: .05, far: 60 }} gl={{ antialias: true, powerPreference: 'high-performance' }} fallback={<div className={styles.fallback}>Enable WebGL to explore the 3D plant room.</div>}>
        <SceneLighting />
        <SceneWorld components={components} selectedId={selectedId} onSelect={onSelect} guides={showGuides} />
        <CameraRig mode={mode} targetId={focused} components={components} resetKey={resetKey} />
        <OverlayProjection components={components} markers={markerElements} compass={compass} refreshKey={`${showMarkers}:${showControls}:${selectedId}`} />
      </Canvas>
    </SceneBoundary>
    {showMarkers && <div className={styles.markerLayer}>{components.map(component => <div key={component.id} className={styles.markerAnchor} ref={element => { if (element) markerElements.current.set(component.id, element); else markerElements.current.delete(component.id); }}>
      <button type="button" className={`${styles.marker} ${styles[component.status]} ${selectedId === component.id ? styles.markerSelected : ''}`} onClick={event => { event.stopPropagation(); onSelect(component.id); }} aria-label={`${component.tag}: ${component.name}, ${component.status}`} title={`${component.tag} · ${component.name}`}>
        <span />
        {selectedId === component.id && <span className={styles.markerLabel}>{component.tag}<small>{component.name}</small></span>}
      </button>
    </div>)}</div>}
    {showControls && <><div className={styles.worldCaption}><span className={styles.worldDot} /> ORIGINAL 3D ENVIRONMENT <span className={styles.worldCaptionSeparator}>/</span> PLANT ROOM 01</div>
    <div className={styles.compass} ref={compass}><span>N</span><small>000°</small></div>
    <div className={styles.worldControls}>
      <button type="button" title={mode === 'orbit' ? 'Switch to walk mode' : 'Switch to orbit mode'} aria-label={mode === 'orbit' ? 'Switch to walk mode' : 'Switch to orbit mode'} className={mode === 'walk' ? styles.controlActive : ''} onClick={() => setMode(value => value === 'orbit' ? 'walk' : 'orbit')}><Move size={14} /><span>{mode === 'walk' ? 'Walk' : 'Orbit'}</span></button>
      {selectedId && <button type="button" title="Focus selected component" onClick={() => { setFocused(null); requestAnimationFrame(() => setFocused(selectedId)); }}><Focus size={14} /><span>Focus</span></button>}
      <button type="button" title="Reset view" onClick={reset}><RotateCcw size={13} /><span>Reset view</span></button>
      <button type="button" aria-label="Fullscreen 3D view" title="Fullscreen 3D view" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void container.current?.requestFullscreen(); }}><Expand size={13} /></button>
    </div>
    <div className={styles.worldHelp}>{mode === 'walk' ? <><span>EXPLORE WITH YOUR KEYBOARD</span><small>W A S D / arrows to move · Q / E down / up · drag to look</small></> : <><span>EXPLORE THE PLANT ROOM</span><small>Drag to orbit · scroll to zoom · click a component to inspect</small></>}</div></>}
  </div>;
}

export const INSPECTION_STATIONS: { name: string; position: Vec3; target: Vec3; focusId: string; direction: string }[] = [
  { name: 'Pumps and pipework', position: [-4.6, 1.8, 3.2], target: [-1.5, 1.5, -.7], focusId: 'pump-01', direction: '270°' },
  { name: 'Overhead services', position: [1.6, 2.2, 4.1], target: [-1.6, 3.3, -2.4], focusId: 'duct-01', direction: '270°' },
  { name: 'Rear wall', position: [0, 1.75, .9], target: [.3, 1.8, -5], focusId: 'exchanger-01', direction: '225°' },
  { name: 'Second aisle', position: [-2.1, 1.8, 2], target: [-3.2, 2.1, -.6], focusId: 'valve-01', direction: '225°' },
  { name: 'Exit lighting wall', position: [-3.7, 1.8, .4], target: [-1, 2.0, 5.1], focusId: 'light-01', direction: '225°' },
  { name: 'West end', position: [-.3, 1.7, -.2], target: [-5.7, 1.7, -2.8], focusId: 'panel-01', direction: '270°' },
  { name: 'East bay', position: [.9, 1.8, 2.7], target: [4.3, 1.5, -2.5], focusId: 'tank-02', direction: '225°' },
  { name: 'South-west corner', position: [-5.7, 1.7, 4.5], target: [-1.2, 1.5, -.8], focusId: 'pump-02', direction: '225°' },
  { name: 'North-west wall', position: [-4.8, 1.7, -4.7], target: [-3.8, 1.8, 1.6], focusId: 'panel-02', direction: '270°' },
  { name: 'North-east corner', position: [5.5, 2, -5.1], target: [2, 1.4, -1.2], focusId: 'tank-01', direction: '270°' },
  { name: 'West aisle', position: [-4.6, 1.7, 2.7], target: [-4.9, 2, -3.5], focusId: 'sensor-01', direction: '270°' },
  { name: 'South-east aisle', position: [5.5, 1.8, 4.7], target: [.7, 1.8, -.8], focusId: 'pump-03', direction: '225°' },
];

function SnapshotRenderer({ onCapture, signature }: { onCapture: (images: string[]) => void; signature: string }) {
  const { gl, scene, invalidate } = useThree();
  const rendered = useRef(false);
  useEffect(() => { rendered.current = false; invalidate(); }, [signature, invalidate]);
  useFrame(() => {
    if (rendered.current) return;
    rendered.current = true;
    const width = 512, height = 288;
    const renderTarget = new THREE.WebGLRenderTarget(width, height, { samples: 2, colorSpace: THREE.SRGBColorSpace });
    const pixels = new Uint8Array(width * height * 4);
    const flipped = new Uint8ClampedArray(width * height * 4);
    const surface = document.createElement('canvas'); surface.width = width; surface.height = height;
    const context = surface.getContext('2d');
    const camera = new THREE.PerspectiveCamera(64, width / height, .05, 60);
    const previousTarget = gl.getRenderTarget();
    const images: string[] = [];
    try {
      for (const station of INSPECTION_STATIONS) {
        camera.position.set(...station.position); camera.lookAt(...station.target); camera.updateMatrixWorld();
        gl.setRenderTarget(renderTarget); gl.clear(); gl.render(scene, camera);
        gl.readRenderTargetPixels(renderTarget, 0, 0, width, height, pixels);
        for (let row = 0; row < height; row++) flipped.set(pixels.subarray(row * width * 4, (row + 1) * width * 4), (height - row - 1) * width * 4);
        context?.putImageData(new ImageData(flipped, width, height), 0, 0);
        images.push(surface.toDataURL('image/jpeg', .86));
      }
      onCapture(images);
    } finally { gl.setRenderTarget(previousTarget); renderTarget.dispose(); }
  }, 1);
  return null;
}

function PlanMap({ active, onActivate }: { active: number | null; onActivate: (index: number) => void }) {
  const transform = (x: number, z: number) => [130 + x * 15, 130 + z * 15];
  return <svg viewBox="0 0 260 260" className={styles.planSvg} aria-label="Inspection camera positions in the plant room">
    <defs><pattern id="scene-map-grid" width="15" height="15" patternUnits="userSpaceOnUse"><path d="M 15 0 L 0 0 0 15" fill="none" stroke="#34423d" strokeWidth=".5" /></pattern></defs>
    <rect x="29" y="35" width="202" height="190" fill="url(#scene-map-grid)" stroke="#56635a" strokeWidth="1" />
    <path d="M 45 89 H 195 V 69 M 45 111 H 195 V 69" stroke="#7f8e7c" strokeWidth="6" fill="none" opacity=".8" />
    <path d="M 45 89 H 195 V 69 M 45 111 H 195 V 69" stroke="#34463c" strokeWidth="2" fill="none" />
    {[-3.1, -1.2, .7].map(x => { const [cx, cy] = transform(x, -.6); return <g key={x}><rect x={cx - 9} y={cy - 14} width="18" height="28" rx="2" fill="#6b8990" /><circle cx={cx} cy={cy + 3} r="6" fill="#47717d" /></g>; })}
    {[-3.6, -.7].map(z => { const [cx, cy] = transform(4.1, z); return <circle key={z} cx={cx} cy={cy} r="11" fill="#63796f" stroke="#8da18d" />; })}
    <rect x="104" y="48" width="18" height="12" fill="#73847b" /><rect x="143" y="48" width="18" height="12" fill="#73847b" />
    <path d="M 118 225 L 118 208 A 22 22 0 0 1 140 225" stroke="#8a9f8d" strokeWidth="1" fill="none" />
    {INSPECTION_STATIONS.map((station, i) => { const [cx, cy] = transform(station.position[0], station.position[2]); return <g key={station.name} role="button" tabIndex={0} aria-label={`Select camera ${i + 1}: ${station.name}`} onClick={() => onActivate(i)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onActivate(i); } }} className={styles.mapStation}>
      {active === i && <circle cx={cx} cy={cy} r="11" fill="#c6ae5f" opacity=".18" />}
      <circle cx={cx} cy={cy} r={active === i ? 4 : 3} fill={active === i ? '#f2d580' : '#c5b76b'} />
      <text x={cx + 6} y={cy - 4} fill={active === i ? '#f1eedf' : '#9eaca0'} fontSize="7" fontFamily="monospace">S{String(i + 1).padStart(2, '0')}</text>
    </g>; })}
    <path d="M 229 17 V 4 M 225 9 L 229 4 L 233 9" stroke="#afbaaa" strokeWidth="1.2" fill="none" /><text x="226" y="28" fill="#a9b5a5" fontSize="7">N</text>
  </svg>;
}

export function CameraWall({ components, onSelect, running = false }: { components: Component[]; onSelect: (id: string) => void; running?: boolean }) {
  const [images, setImages] = useState<string[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const signature = components.map(component => `${component.id}:${component.position.join(',')}`).join('|');
  const capture = useCallback((captures: string[]) => setImages(captures), []);
  const activate = (index: number) => { setActive(index); onSelect(INSPECTION_STATIONS[index].focusId); };
  useEffect(() => {
    if (expanded === null) return;
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [expanded]);
  return <div className={styles.cameraWall} data-testid="camera-wall">
    <div className={styles.captureCanvas} aria-hidden="true"><SceneBoundary><Canvas frameloop="demand" dpr={1} camera={{ position: INITIAL_POSITION }} gl={{ antialias: true, powerPreference: 'high-performance' }}><SceneLighting shadows={false} /><SceneWorld components={components} /><SnapshotRenderer onCapture={capture} signature={signature} /></Canvas></SceneBoundary></div>
    <div className={styles.cameraGrid}>
      {INSPECTION_STATIONS.map((station, index) => {
        const component = components.find(item => item.id === station.focusId);
        return <div key={station.name} className={`${styles.cameraCard} ${active === index ? styles.cameraCardActive : ''}`}>
          <button type="button" className={styles.cameraImageButton} onClick={() => activate(index)} aria-label={`Inspect ${station.name}`}>
            {images[index] ? <img src={images[index]} alt={`3D inspection view: ${station.name}`} className={styles.cameraImage} /> : <div className={styles.cameraPlaceholder}><Camera size={20} /><span>Rendering scene</span></div>}
            <span className={`${styles.cameraState} ${running ? styles.cameraAnalyzing : ''}`}>{running ? <ScanLine size={9} /> : <span className={styles.cameraStateDot} />}{running ? 'Analyzing' : 'Captured'}</span>
            <span className={styles.cameraCorner}>CAM {String(index + 1).padStart(2, '0')}</span>
          </button>
          <div className={styles.cameraCardBottom}>
            <button type="button" onClick={() => activate(index)} className={styles.cameraTitle}>S{String(index + 1).padStart(2, '0')} · {station.name}</button>
            <div className={styles.cameraMeta}><span>{station.direction}</span><div className={styles.detectionDots} title={`${component?.name ?? station.name}: ${component?.status ?? 'unknown'}`}>{Array.from({ length: 9 }, (_, i) => <i key={i} className={i === 3 && component?.status === 'issue' ? styles.dotIssue : i < (component?.status === 'verified' ? 8 : 5) ? styles.dotVerified : styles.dotPending} />)}</div><button type="button" aria-label={`Expand ${station.name}`} title="Expand inspection image" onClick={() => setExpanded(index)}><ArrowUpRight size={11} /></button></div>
          </div>
        </div>;
      })}
    </div>
    <aside className={styles.mapPanel}>
      <div className={styles.mapHeading}><LocateFixed size={12} /><span>TOP-DOWN MAP</span></div>
      <PlanMap active={active} onActivate={activate} />
      <div className={styles.mapLegend}><span><i /> Inspection station</span><span>12 viewpoints</span></div>
      <div className={styles.mapDetails}><span className={styles.mapEyebrow}>SPATIAL COVERAGE</span><strong>{active === null ? 'Plant room survey' : INSPECTION_STATIONS[active].name}</strong><p>{active === null ? 'Select a camera or map position to inspect equipment from that viewpoint.' : `${INSPECTION_STATIONS[active].focusId.toUpperCase()} · linked to the component register and its requirements.`}</p></div>
      <div className={styles.mapNotice}><span className={styles.worldDot} /><span>Views rendered from the local 3D model.<br />{running ? 'Inspection job running on the backend.' : 'Ready for an inspection run.'}</span></div>
    </aside>
    {expanded !== null && <div className={styles.expandedBackdrop} role="dialog" aria-modal="true" aria-label={INSPECTION_STATIONS[expanded].name} onClick={() => setExpanded(null)}><div className={styles.expandedView} onClick={event => event.stopPropagation()}><div><span>S{String(expanded + 1).padStart(2, '0')} · {INSPECTION_STATIONS[expanded].name}</span><button type="button" onClick={() => setExpanded(null)}>Close</button></div>{images[expanded] && <img src={images[expanded]} alt={INSPECTION_STATIONS[expanded].name} />}<button type="button" className={styles.inspectExpanded} onClick={() => { activate(expanded); setExpanded(null); }}><Focus size={14} /> Inspect linked component</button></div></div>}
  </div>;
}
