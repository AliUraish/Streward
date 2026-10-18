'use client';

import { useEffect, useMemo } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import type { Component, Vec3 } from '../../../../shared/types';

// All geometry is original and generated locally. Positions refer to shared/scene.json.
// Shared primitive buffers and materials keep the scene practical on integrated GPUs.
const boxGeometry = new THREE.BoxGeometry(1, 1, 1);
const cylinderGeometry = new THREE.CylinderGeometry(1, 1, 1, 20);
const sphereGeometry = new THREE.SphereGeometry(1, 20, 12);
const diskGeometry = new THREE.CircleGeometry(1, 32);
const wheelGeometry = new THREE.TorusGeometry(1, .105, 8, 32);
const flangeGeometry = new THREE.TorusGeometry(1, .065, 6, 24);
const materials = {
  blue: new THREE.MeshStandardMaterial({ color: '#175b80', metalness: .62, roughness: .37 }),
  blueDark: new THREE.MeshStandardMaterial({ color: '#183a4e', metalness: .66, roughness: .42 }),
  teal: new THREE.MeshStandardMaterial({ color: '#267d88', metalness: .56, roughness: .4 }),
  insulation: new THREE.MeshStandardMaterial({ color: '#d7d8d2', metalness: .16, roughness: .63 }),
  steel: new THREE.MeshStandardMaterial({ color: '#838f90', metalness: .8, roughness: .34 }),
  dark: new THREE.MeshStandardMaterial({ color: '#343d3e', metalness: .64, roughness: .5 }),
  black: new THREE.MeshStandardMaterial({ color: '#202728', metalness: .12, roughness: .7 }),
  red: new THREE.MeshStandardMaterial({ color: '#9e3538', metalness: .5, roughness: .39 }),
  brass: new THREE.MeshStandardMaterial({ color: '#b69b58', metalness: .72, roughness: .32 }),
  cabinet: new THREE.MeshStandardMaterial({ color: '#c2c8c2', metalness: .45, roughness: .42 }),
  paper: new THREE.MeshStandardMaterial({ color: '#e4e3d9', roughness: .85 }),
  yellow: new THREE.MeshStandardMaterial({ color: '#d1ac45', metalness: .12, roughness: .58 }),
  selected: new THREE.MeshStandardMaterial({ color: '#6ad4af', emissive: '#2f795e', emissiveIntensity: .1, metalness: .4, roughness: .32 }),
  light: new THREE.MeshStandardMaterial({ color: '#f0eee0', emissive: '#ffffee', emissiveIntensity: 2.4, roughness: .4 }),
  green: new THREE.MeshStandardMaterial({ color: '#78d69a', emissive: '#2b6f49', emissiveIntensity: .8 }),
};
type MaterialName = keyof typeof materials;
const vectorUp = new THREE.Vector3(0, 1, 0);

function Box({ position = [0, 0, 0], size, material = 'steel', rotation, cast = true }: {
  position?: Vec3; size: Vec3; material?: MaterialName; rotation?: Vec3; cast?: boolean;
}) {
  return <mesh geometry={boxGeometry} material={materials[material]} position={position} scale={size} rotation={rotation} castShadow={cast} receiveShadow />;
}

function Cylinder({ position = [0, 0, 0], radius, length, material = 'steel', rotation }: {
  position?: Vec3; radius: number; length: number; material?: MaterialName; rotation?: Vec3;
}) {
  return <mesh geometry={cylinderGeometry} material={materials[material]} position={position} scale={[radius, length, radius]} rotation={rotation} castShadow receiveShadow />;
}

function Pipe({ from, to, radius = .16, material = 'insulation' }: {
  from: Vec3; to: Vec3; radius?: number; material?: MaterialName;
}) {
  const { midpoint, quaternion, length } = useMemo(() => {
    const start = new THREE.Vector3(...from);
    const end = new THREE.Vector3(...to);
    const direction = end.clone().sub(start);
    return {
      midpoint: start.add(end).multiplyScalar(.5),
      quaternion: new THREE.Quaternion().setFromUnitVectors(vectorUp, direction.clone().normalize()),
      length: direction.length(),
    };
  }, [from[0], from[1], from[2], to[0], to[1], to[2]]);
  return <mesh geometry={cylinderGeometry} material={materials[material]} position={midpoint} quaternion={quaternion} scale={[radius, length, radius]} castShadow receiveShadow />;
}

function Elbow({ at, radius = .16, material = 'insulation' }: { at: Vec3; radius?: number; material?: MaterialName }) {
  return <mesh geometry={sphereGeometry} position={at} scale={radius} material={materials[material]} castShadow receiveShadow />;
}

function Flange({ position, radius = .24, rotation = [0, 0, 0] }: { position: Vec3; radius?: number; rotation?: Vec3 }) {
  return <group position={position} rotation={rotation}>
    <Cylinder radius={radius} length={.085} material="red" />
    <Cylinder position={[0, -.057, 0]} radius={radius * .95} length={.025} material="steel" />
    {[0, 1, 2, 3, 4, 5].map(i => <Cylinder key={i} radius={.022} length={.13} material="steel" position={[
      Math.cos(i * Math.PI / 3) * radius * .77, 0, Math.sin(i * Math.PI / 3) * radius * .77,
    ]} />)}
  </group>;
}

function ValveWheel({ radius = .23 }: { radius?: number }) {
  return <group>
    <mesh geometry={wheelGeometry} material={materials.red} scale={radius} castShadow />
    <Cylinder radius={.045} length={.09} material="red" rotation={[Math.PI / 2, 0, 0]} />
    {[0, Math.PI / 3, Math.PI * 2 / 3].map(a => <Box key={a} size={[radius * 1.9, .023, .026]} rotation={[0, 0, a]} material="red" />)}
  </group>;
}

function GaugeFace({ selected = false }: { selected?: boolean }) {
  return <group>
    <Cylinder radius={.145} length={.07} rotation={[Math.PI / 2, 0, 0]} material={selected ? 'selected' : 'steel'} />
    <mesh position={[0, 0, .04]} geometry={diskGeometry} material={materials.paper} scale={.128} />
    {Array.from({ length: 11 }, (_, i) => {
      const angle = (i / 10) * Math.PI * 1.5 + Math.PI * .75;
      return <Box key={i} position={[Math.cos(angle) * .103, Math.sin(angle) * .103, .045]} size={[.018, .006, .004]} rotation={[0, 0, angle]} material="black" cast={false} />;
    })}
    <Box position={[.025, .024, .05]} size={[.09, .008, .006]} rotation={[0, 0, Math.PI / 4]} material="red" cast={false} />
    <Cylinder position={[0, 0, .053]} radius={.013} length={.008} rotation={[Math.PI / 2, 0, 0]} material="black" />
  </group>;
}

function Pump({ selected }: { selected: boolean }) {
  const body: MaterialName = selected ? 'selected' : 'blue';
  return <group>
    <Box position={[0, .1, 0]} size={[1.25, .2, 1.8]} material="dark" />
    <Box position={[0, .24, 0]} size={[1.02, .08, 1.5]} material="steel" />
    {[-.43, .43].flatMap(x => [-.65, .65].map(z => <Cylinder key={`${x}-${z}`} position={[x, .31, z]} radius={.035} length={.13} material="brass" />))}
    <Box position={[0, .43, 0]} size={[.53, .3, 1.0]} material={body} />
    <Cylinder position={[0, .75, -.36]} radius={.36} length={.31} rotation={[Math.PI / 2, 0, 0]} material={body} />
    <mesh geometry={flangeGeometry} position={[0, .75, -.19]} scale={.33} material={materials.steel} castShadow />
    <Cylinder position={[0, .75, -.68]} radius={.18} length={.37} rotation={[Math.PI / 2, 0, 0]} material="blueDark" />
    <Cylinder position={[0, .75, .28]} radius={.31} length={.9} rotation={[Math.PI / 2, 0, 0]} material={body} />
    {Array.from({ length: 8 }, (_, i) => <Cylinder key={i} position={[0, .75, -.04 + i * .1]} radius={.327} length={.025} rotation={[Math.PI / 2, 0, 0]} material="blueDark" />)}
    <Cylinder position={[0, .75, .79]} radius={.34} length={.13} rotation={[Math.PI / 2, 0, 0]} material="blueDark" />
    <Box position={[.18, 1.03, .3]} size={[.34, .25, .4]} material="blueDark" />
    <Box position={[.18, 1.165, .3]} size={[.35, .02, .41]} material="steel" />
    <Pipe from={[0, 1, -.36]} to={[0, 1, 0]} radius={.15} />
    <Elbow at={[0, 1, 0]} radius={.15} />
    <Pipe from={[0, 1, 0]} to={[0, 2.98, 0]} radius={.15} />
    <Flange position={[0, 1.42, 0]} />
    <Flange position={[0, 2.1, 0]} />
    <Pipe from={[0, .75, -.8]} to={[0, .75, -1.18]} radius={.14} material="steel" />
    <Elbow at={[0, .75, -1.18]} radius={.14} material="steel" />
    <Pipe from={[0, .75, -1.18]} to={[0, 3, -1.18]} radius={.14} />
    <Flange position={[0, 1.9, -1.18]} radius={.22} />
    <Box position={[0, .86, 1.13]} size={[.28, .12, .018]} material="paper" />
    <Pipe from={[.35, .95, .4]} to={[.58, .64, .5]} radius={.025} material="black" />
    <Pipe from={[.58, .64, .5]} to={[.58, .2, 1.1]} radius={.025} material="black" />
  </group>;
}

function Tank({ selected, tall = false }: { selected: boolean; tall?: boolean }) {
  const height = tall ? 2.8 : 2.25;
  const body: MaterialName = selected ? 'selected' : tall ? 'insulation' : 'teal';
  return <group>
    {[0, 1, 2].map(i => <Box key={i} position={[Math.cos(i * Math.PI * 2 / 3) * .46, .21, Math.sin(i * Math.PI * 2 / 3) * .46]} size={[.14, .42, .14]} material="dark" />)}
    <Cylinder position={[0, height / 2 + .4, 0]} radius={.64} length={height - .45} material={body} />
    <mesh position={[0, .62, 0]} geometry={sphereGeometry} scale={[.64, .38, .64]} material={materials[body]} castShadow />
    <mesh position={[0, height + .15, 0]} geometry={sphereGeometry} scale={[.64, .38, .64]} material={materials[body]} castShadow />
    {[.9, height - .05].map(y => <Cylinder key={y} position={[0, y, 0]} radius={.653} length={.04} material="steel" />)}
    <Pipe from={[0, height + .4, 0]} to={[0, 3.4, 0]} radius={.075} material="steel" />
    <Pipe from={[0, .52, .4]} to={[0, .52, 1]} radius={.085} material="steel" />
    <Box position={[0, height * .65, .646]} size={[.33, .22, .022]} material="paper" />
    <Box position={[0, height * .65 + .06, .66]} size={[.24, .018, .008]} material="black" />
    <group position={[.33, height * .65, .58]} rotation={[0, .45, 0]}><GaugeFace /></group>
    <Cylinder position={[-.38, 1.3, .52]} radius={.026} length={1.5} material="brass" />
  </group>;
}

function HeatExchanger({ selected }: { selected: boolean }) {
  return <group>
    <Box position={[0, .13, 0]} size={[1.26, .25, .8]} material="dark" />
    <Box position={[0, 1.01, 0]} size={[1.08, 1.58, .32]} material={selected ? 'selected' : 'blue'} />
    {Array.from({ length: 17 }, (_, i) => <Box key={i} position={[0, .35 + i * .078, .195]} size={[.9, .018, .085]} material="steel" />)}
    {[-.44, .44].flatMap(x => [.49, 1.6].map(y => <Cylinder key={`${x}-${y}`} position={[x, y, .25]} radius={.055} length={.63} rotation={[Math.PI / 2, 0, 0]} material="steel" />))}
    {[-.35, .35].flatMap(x => [.63, 1.43].map(y => <group key={`${x}-${y}`}>
      <Pipe from={[x, y, .21]} to={[x, y, .85]} radius={.095} material="steel" />
      <Flange position={[x, y, .7]} radius={.14} rotation={[Math.PI / 2, 0, 0]} />
      <Pipe from={[x, y, .85]} to={[x, 3.35, .85]} radius={.1} />
    </group>))}
    <Box position={[0, 1.06, .28]} size={[.28, .17, .012]} material="paper" />
  </group>;
}

function Panel({ selected }: { selected: boolean }) {
  return <group rotation={[0, Math.PI / 2, 0]}>
    <Box position={[0, .52, 0]} size={[1.2, 1.8, .4]} material="dark" />
    <Box position={[0, .52, .22]} size={[1.14, 1.74, .04]} material={selected ? 'selected' : 'cabinet'} />
    <Box position={[.42, .52, .26]} size={[.035, .2, .035]} material="black" />
    <Box position={[-.05, .9, .26]} size={[.48, .27, .025]} material="dark" />
    <Box position={[-.05, .9, .28]} size={[.36, .15, .01]} material="teal" />
    {[0, 1, 2].map(i => <Cylinder key={i} position={[-.28 + i * .24, .56, .27]} radius={.035} length={.035} rotation={[Math.PI / 2, 0, 0]} material={i === 0 ? 'green' : i === 1 ? 'red' : 'black'} />)}
    <Box position={[0, .19, .25]} size={[.3, .19, .02]} material="yellow" />
    {Array.from({ length: 5 }, (_, i) => <Box key={i} position={[0, -.15 - i * .065, .25]} size={[.55, .018, .015]} material="dark" />)}
    {[-.33, 0, .33].map(x => <Pipe key={x} from={[x, 1.4, -.04]} to={[x, 2.65, -.04]} radius={.024} material="steel" />)}
  </group>;
}

function Valve({ selected, horizontal }: { selected: boolean; horizontal?: boolean }) {
  return <group>
    <Cylinder radius={.19} length={.34} material={selected ? 'selected' : 'blueDark'} rotation={horizontal ? [0, 0, Math.PI / 2] : [0, 0, 0]} />
    <Flange position={horizontal ? [-.2, 0, 0] : [0, -.2, 0]} rotation={horizontal ? [0, 0, Math.PI / 2] : [0, 0, 0]} radius={.235} />
    <Flange position={horizontal ? [.2, 0, 0] : [0, .2, 0]} rotation={horizontal ? [0, 0, Math.PI / 2] : [0, 0, 0]} radius={.235} />
    <Pipe from={[0, 0, .12]} to={[0, 0, .37]} radius={.038} material="brass" />
    <group position={[0, 0, .4]}><ValveWheel /></group>
  </group>;
}

function Duct({ selected }: { selected: boolean }) {
  return <group>
    <Box size={[.8, .62, 4.4]} material={selected ? 'selected' : 'steel'} />
    {[-2, -1, 0, 1, 2].map(z => <group key={z}>
      <Box position={[0, 0, z]} size={[.83, .65, .036]} material="dark" />
      <Pipe from={[-.48, 0, z]} to={[-.48, .8, z]} radius={.018} material="steel" />
      <Pipe from={[.48, 0, z]} to={[.48, .8, z]} radius={.018} material="steel" />
      <Box position={[0, -.35, z]} size={[1.05, .055, .08]} material="steel" />
    </group>)}
  </group>;
}

function Sensor({ selected }: { selected: boolean }) {
  return <group>
    <Box size={[.18, .23, .13]} material={selected ? 'selected' : 'steel'} />
    <Box position={[0, .03, .07]} size={[.12, .08, .012]} material="dark" />
    <Pipe from={[0, -.1, 0]} to={[0, -.32, 0]} radius={.025} material="brass" />
    <Pipe from={[0, .1, -.02]} to={[0, .45, -.02]} radius={.013} material="black" />
  </group>;
}

function FireExtinguisher({ selected }: { selected: boolean }) {
  return <group>
    <Box position={[.09, .21, -.05]} size={[.12, .55, .15]} material="dark" />
    <Cylinder position={[0, .25, .13]} radius={.14} length={.64} material={selected ? 'selected' : 'red'} />
    <mesh position={[0, .58, .13]} geometry={sphereGeometry} scale={[.14, .12, .14]} material={materials.red} castShadow />
    <Cylinder position={[0, .72, .13]} radius={.035} length={.15} material="brass" />
    <Box position={[.05, .8, .13]} size={[.25, .035, .06]} material="black" />
    <Box position={[0, .29, .27]} size={[.18, .27, .015]} material="paper" />
    <Pipe from={[.13, .65, .1]} to={[.22, .08, .1]} radius={.025} material="black" />
  </group>;
}

function Door({ selected }: { selected: boolean }) {
  return <group>
    <Box position={[0, 1.3, 0]} size={[1.6, 2.6, .12]} material="dark" />
    <Box position={[0, 1.27, -.08]} size={[1.43, 2.45, .05]} material={selected ? 'selected' : 'cabinet'} />
    <Box position={[.5, 1.18, -.13]} size={[.06, .16, .06]} material="steel" />
    <Box position={[.41, 1.18, -.17]} size={[.25, .035, .06]} material="steel" />
    <Box position={[0, 2.86, -.03]} size={[.75, .23, .08]} material="green" />
    <Box position={[0, 2.87, -.08]} size={[.36, .035, .015]} material="paper" />
    <Box position={[0, .018, -.63]} size={[2.6, .025, .08]} material="yellow" />
  </group>;
}

export function AssetGeometry({ component, selected = false }: { component: Component; selected?: boolean }) {
  switch (component.kind) {
    case 'pump': return <Pump selected={selected} />;
    case 'tank': return <Tank selected={selected} tall={component.id === 'tank-02'} />;
    case 'exchanger': return <HeatExchanger selected={selected} />;
    case 'panel': return <Panel selected={selected} />;
    case 'valve': return <Valve selected={selected} horizontal={['valve-04', 'valve-05'].includes(component.id)} />;
    case 'gauge': return <group><Pipe from={[0, -.2, -.16]} to={[0, 0, -.16]} radius={.026} material="brass" /><GaugeFace selected={selected} /></group>;
    case 'duct': return <Duct selected={selected} />;
    case 'sensor': return <Sensor selected={selected} />;
    case 'light': return <group><Box size={[.7, .16, .15]} material={selected ? 'selected' : 'cabinet'} /><Box position={[0, -.1, .04]} size={[.6, .08, .08]} material="light" /></group>;
    case 'fire': return <FireExtinguisher selected={selected} />;
    case 'door': return <Door selected={selected} />;
    default: return <Box size={[.4, .4, .4]} material={selected ? 'selected' : 'steel'} />;
  }
}

function createSurface(kind: 'floor' | 'wall') {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size; canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) return undefined;
  let seed = kind === 'floor' ? 431 : 933;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const data = context.createImageData(size, size);
  const base = kind === 'floor' ? [138, 139, 128] : [145, 146, 136];
  for (let i = 0; i < data.data.length; i += 4) {
    const noise = (random() - .5) * 27;
    data.data[i] = base[0] + noise;
    data.data[i + 1] = base[1] + noise;
    data.data[i + 2] = base[2] + noise;
    data.data[i + 3] = 255;
  }
  context.putImageData(data, 0, 0);
  if (kind === 'wall') {
    context.strokeStyle = '#73766f'; context.lineWidth = 2;
    for (let y = 0; y <= size; y += 128) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(size, y); context.stroke();
      for (let x = (y / 128) % 2 ? 0 : 128; x < size; x += 256) {
        context.beginPath(); context.moveTo(x, y); context.lineTo(x, y + 128); context.stroke();
      }
    }
  } else {
    context.strokeStyle = 'rgba(55,61,55,.25)'; context.lineWidth = 1;
    context.strokeRect(0, 0, size, size);
    for (let i = 0; i < 120; i++) {
      context.fillStyle = `rgba(70,72,65,${random() * .08})`;
      context.beginPath(); context.ellipse(random() * size, random() * size, 5 + random() * 40, 3 + random() * 20, random() * Math.PI, 0, Math.PI * 2); context.fill();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(kind === 'floor' ? 5 : 3, kind === 'floor' ? 5 : 1.5);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function Architecture() {
  const floorTexture = useMemo(() => createSurface('floor'), []);
  const wallTexture = useMemo(() => createSurface('wall'), []);
  useEffect(() => () => { floorTexture?.dispose(); wallTexture?.dispose(); }, [floorTexture, wallTexture]);
  return <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[13, 12]} />
      <meshStandardMaterial map={floorTexture} roughness={.92} metalness={.03} />
    </mesh>
    <mesh position={[0, 2.3, -6]} receiveShadow>
      <planeGeometry args={[13, 4.6]} />
      <meshStandardMaterial map={wallTexture} roughness={.95} />
    </mesh>
    <mesh position={[-6.5, 2.3, 0]} rotation={[0, Math.PI / 2, 0]} receiveShadow>
      <planeGeometry args={[12, 4.6]} />
      <meshStandardMaterial map={wallTexture} roughness={.95} />
    </mesh>
    <mesh position={[6.5, 2.3, 0]} rotation={[0, -Math.PI / 2, 0]} receiveShadow>
      <planeGeometry args={[12, 4.6]} />
      <meshStandardMaterial map={wallTexture} roughness={.95} />
    </mesh>
    <mesh position={[0, 4.6, 0]} rotation={[Math.PI / 2, 0, 0]}>
      <planeGeometry args={[13, 12]} />
      <meshStandardMaterial color="#a2a59b" roughness={.92} />
    </mesh>
    {[-6.3, 6.3].map(x => <Box key={x} position={[x, .14, 0]} size={[.12, .28, 12]} material="dark" />)}
    <Box position={[0, .14, -5.9]} size={[13, .28, .12]} material="dark" />
    {[-5.9, -.2, 5.9].map(x => <Box key={x} position={[x, 2.3, -5.9]} size={[.3, 4.6, .22]} material="cabinet" />)}
    {[-3.8, 1.1].map(z => <Box key={z} position={[0, 4.38, z]} size={[12.9, .32, .25]} material="dark" />)}
    {[-4.2, -.5, 3.2].map(z => <group key={z}>
      <Box position={[0, 4.12, z]} size={[1.55, .07, .26]} material="dark" />
      <Box position={[0, 4.06, z]} size={[1.45, .045, .19]} material="light" />
    </group>)}
    {[-4, -.5, 3.8].map(x => <group key={x}>
      <Box position={[x, .012, 2.3]} size={[.07, .015, 4.3]} material="yellow" cast={false} />
      <Box position={[x, .015, -.95]} size={[.07, .02, 1.3]} material="yellow" cast={false} />
    </group>)}
    <Box position={[-1.15, .013, 2.6]} size={[4.6, .017, .07]} material="yellow" cast={false} />
    {/* Suspended ladder tray with cross ties. */}
    {[-.39, .39].map(x => <Box key={x} position={[x + 2.7, 3.62, 0]} size={[.065, .14, 10.5]} material="steel" />)}
    {Array.from({ length: 27 }, (_, i) => <Box key={i} position={[2.7, 3.56, -5.1 + i * .4]} size={[.8, .045, .045]} material="steel" />)}
    {[0, 1, 2].map(i => <Pipe key={i} from={[2.5 + i * .13, 3.64, -5.3]} to={[2.5 + i * .13, 3.64, 5.3]} radius={.026} material="black" />)}
    {[-4, -1.6, .8, 3.2].map(z => <group key={z}>
      <Pipe from={[2.2, 3.58, z]} to={[2.2, 4.56, z]} radius={.015} material="steel" />
      <Pipe from={[3.2, 3.58, z]} to={[3.2, 4.56, z]} radius={.015} material="steel" />
    </group>)}
    {/* Back-wall service pipes and their brackets. */}
    {[2.1, 2.5, 2.9].map((y, i) => <group key={y}>
      <Pipe from={[-5.9, y, -5.55]} to={[5.8, y, -5.55]} radius={i === 2 ? .12 : .075} material={i === 2 ? 'insulation' : 'steel'} />
      {[-4.8, -2.5, 0, 2.5, 4.9].map(x => <Box key={x} position={[x, y, -5.7]} size={[.055, .35, .35]} material="dark" />)}
    </group>)}
    {/* A drain and a service ladder give the room a useful sense of scale. */}
    <Box position={[3.2, .009, 2.8]} size={[.5, .025, .5]} material="dark" cast={false} />
    {Array.from({ length: 7 }, (_, i) => <Box key={i} position={[3.2, .025, 2.6 + i * .065]} size={[.43, .02, .025]} material="steel" cast={false} />)}
    {[-.35, .35].map(x => <Box key={x} position={[x + 5.8, 2.03, -5.45]} size={[.06, 4.05, .06]} material="steel" />)}
    {Array.from({ length: 13 }, (_, i) => <Pipe key={i} from={[5.45, .25 + i * .29, -5.45]} to={[6.15, .25 + i * .29, -5.45]} radius={.025} material="steel" />)}
  </group>;
}

function Distribution() {
  return <group>
    {[-.6, 1].map((z, i) => <group key={z}>
      <Pipe from={[-5.6, 3, z]} to={[4.1, 3, z]} radius={.22} />
      <Elbow at={[4.1, 3, z]} radius={.22} />
      <Pipe from={[4.1, 3, z]} to={[4.1, 3, -5.1]} radius={.22} />
      <Pipe from={[-5.6, 3, z]} to={[-5.6, .6, z]} radius={.22} />
      <Elbow at={[-5.6, 3, z]} radius={.22} />
      <Flange position={[-5.6, 1.2, z]} radius={.29} />
      {[-4.7, -2.2, .1, 2.1].map(x => <group key={x}>
        <Flange position={[x, 3, z]} radius={.28} rotation={[0, 0, Math.PI / 2]} />
        <Pipe from={[x, 3.23, z]} to={[x, 4.56, z]} radius={.016} material="steel" />
        <Box position={[x, 3.04, z]} size={[.05, .5, .54]} material="steel" />
      </group>)}
      <group position={[-5.6, 1.7, z]}><ValveWheel radius={.3} /></group>
      {[-3.1, -1.2, .7].map(x => <group key={x}>
        {i === 1 && <Pipe from={[x, 3, -1.78]} to={[x, 3, z]} radius={.15} />}
        <Elbow at={[x, 3, i === 0 ? -.6 : -1.78]} radius={.15} />
      </group>)}
    </group>)}
    <Pipe from={[4.1, 3.4, -3.6]} to={[4.1, 3.4, -.7]} radius={.09} material="steel" />
    <Pipe from={[-5.8, 3.3, -3.6]} to={[-5.8, 3.3, 3.8]} radius={.032} material="steel" />
    <Pipe from={[-5.8, 3.3, 3.8]} to={[-5.5, 3.3, 3.8]} radius={.032} material="steel" />
  </group>;
}

export function SceneLighting({ shadows = true }: { shadows?: boolean }) {
  return <>
    <color attach="background" args={['#1e2828']} />
    <fog attach="fog" args={['#273132', 15, 32]} />
    <ambientLight intensity={.65} color="#e5e9d9" />
    <hemisphereLight args={['#e3e5d8', '#3f4b48', 1.35]} />
    <directionalLight position={[1.5, 6, 3]} intensity={2.1} color="#fff5de" castShadow={shadows} shadow-mapSize={[2048, 2048]} shadow-camera-left={-9} shadow-camera-right={9} shadow-camera-top={8} shadow-camera-bottom={-8} shadow-camera-near={.1} shadow-camera-far={18} shadow-bias={-.0003} shadow-normalBias={.035} />
    <pointLight position={[-4, 3.8, -.5]} intensity={26} decay={2} distance={11} color="#d5e8ef" />
    <pointLight position={[4, 3.8, -3]} intensity={32} decay={2} distance={12} color="#fff1d9" />
    <pointLight position={[0, 3.8, 3.8]} intensity={18} decay={2} distance={10} color="#f0f6ee" />
  </>;
}

export const MARKER_HEIGHT: Record<string, number> = { pump: 1.08, tank: 1.9, exchanger: 1.35, panel: .6, valve: .07, gauge: .03, duct: .05, sensor: .05, light: .1, fire: .5, door: 1.35 };
const NO_SELECTION = () => {};

export function SceneWorld({ components, selectedId = null, onSelect = NO_SELECTION, guides = false }: {
  components: Component[]; selectedId?: string | null; onSelect?: (id: string) => void; guides?: boolean;
}) {
  const click = (event: ThreeEvent<MouseEvent>, id: string) => {
    event.stopPropagation(); onSelect(id);
  };
  return <group dispose={null}>
    <Architecture />
    <Distribution />
    {components.map(component => <group key={component.id} position={component.position} rotation={component.rotation} name={component.id} onClick={event => click(event, component.id)} onPointerOver={event => { event.stopPropagation(); document.body.style.cursor = 'pointer'; }} onPointerOut={() => { document.body.style.cursor = ''; }}>
      <AssetGeometry component={component} selected={selectedId === component.id} />
      {guides && component.kind === 'pump' && <group position={[0, .02, 0]}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[1.02, 1.04, 64]} />
          <meshBasicMaterial color="#a1d8c0" transparent opacity={.65} side={THREE.DoubleSide} />
        </mesh>
      </group>}
    </group>)}
  </group>;
}
