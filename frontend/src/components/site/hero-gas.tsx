"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, type MutableRefObject } from "react";
import * as THREE from "three";
import { PIPE_R, PIPE_Y, VOLUTE_R, VOLUTE_Y, WORLD_CY, WORLD_H, WORLD_W, X, type V2 } from "./story";
import { GAS_TUBES, TANK } from "./hero-sketch";

const vertexShader = /* glsl */ `
  varying vec2 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xy;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const v2 = (p: V2) => `vec2(${p[0].toFixed(4)}, ${p[1].toFixed(4)})`;
const fragmentShader = /* glsl */ `
  precision highp sampler3D;
  uniform sampler3D uNoise;
  uniform float uTime;
  uniform float uInk;
  varying vec2 vWorld;
  out vec4 gasColor;

  float tubeDepth(vec2 p, vec2 a, vec2 b, float r) {
    vec2 ab = b - a;
    vec2 q = p - a - ab * clamp(dot(p - a, ab) / dot(ab, ab), 0.0, 1.0);
    return sqrt(max(0.0, r * r - dot(q, q)));
  }
  float pumpDepth(vec2 p, float x) {
    vec2 q = (p - vec2(x, ${VOLUTE_Y.toFixed(4)})) / ${(VOLUTE_R - 0.025).toFixed(4)};
    return 0.28 * sqrt(max(0.0, 1.0 - dot(q, q)));
  }
  float noiseAt(vec3 p) { return texture(uNoise, p).r; }

  // Advected coordinates stretch the density along the pipe and turn it through the branches.
  vec3 flowCoordinate(vec3 p) {
    vec3 q = vec3(p.x - uTime * 0.56, (p.y - ${PIPE_Y.toFixed(4)}) * 3.6, p.z * 3.0);
    ${[X.p101, X.p102, X.tank].map(x => `
      if (abs(p.x - ${x.toFixed(4)}) < 0.11 && p.y < ${(PIPE_Y - PIPE_R).toFixed(4)})
        q = vec3(p.y - uTime * 0.40 + ${x.toFixed(4)}, (p.x - ${x.toFixed(4)}) * 3.6, p.z * 3.0);
    `).join("")}
    ${[X.p101, X.p102].map((x, i) => `
      if (distance(p.xy, vec2(${x.toFixed(4)}, ${VOLUTE_Y.toFixed(4)})) < ${VOLUTE_R.toFixed(4)}) {
        vec2 d = p.xy - vec2(${x.toFixed(4)}, ${VOLUTE_Y.toFixed(4)});
        float angle = uTime * ${i ? "-0.5" : "0.5"} + length(d) * 2.2;
        q = vec3(mat2(cos(angle), -sin(angle), sin(angle), cos(angle)) * d * 1.7, p.z * 2.4);
        q.z -= uTime * 0.12;
      }
    `).join("")}
    if (p.x > ${(X.tank - TANK.r).toFixed(4)} && p.y < ${(TANK.top + TANK.r).toFixed(4)}) {
      q = vec3((p.x - ${X.tank.toFixed(4)}) * 1.1, p.y * 0.8 - uTime * 0.15, p.z);
      q.x += sin(p.y * 3.0 - uTime * 0.45) * 0.16;
    }
    return q;
  }

  void main() {
    vec2 p = vWorld;
    float depth = 0.0;
    ${GAS_TUBES.map(t => `depth = max(depth, tubeDepth(p, ${v2(t.a)}, ${v2(t.b)}, ${t.r.toFixed(4)}));`).join("\n")}
    depth = max(depth, pumpDepth(p, ${X.p101.toFixed(4)}));
    depth = max(depth, pumpDepth(p, ${X.p102.toFixed(4)}));
    depth = max(depth, tubeDepth(p, vec2(${X.tank.toFixed(4)}, ${TANK.bottom.toFixed(4)}), vec2(${X.tank.toFixed(4)}, ${TANK.top.toFixed(4)}), ${(TANK.r - 0.025).toFixed(4)}));

    float plume = 0.0;
    float h = p.y - ${(PIPE_Y + 0.49).toFixed(4)};
    if (h > 0.0 && h < 1.55) {
      float width = 0.025 + h * 0.15 + h * h * 0.035;
      float drift = sin(h * 5.0 - uTime * 0.8) * h * 0.065 + h * 0.045;
      float across = (p.x - ${X.v504.toFixed(4)} - drift) / width;
      if (abs(across) < 2.4) {
        vec3 q = vec3(across * 0.19, h * 0.8 - uTime * 0.34, uTime * 0.035);
        float billow = noiseAt(q * 0.7);
        float wisp = noiseAt(q * 1.9 + billow * 0.22);
        plume = exp(-across * across * 1.7) * smoothstep(0.0, 0.07, h);
        plume *= 1.0 - smoothstep(0.5, 1.55, h);
        plume *= smoothstep(0.28, 0.72, billow * 0.65 + wisp * 0.35) * 0.62;
      }
    }
    if (depth <= 0.0 && plume < 0.002) discard;

    float transmittance = 1.0;
    float light = 0.0;
    if (depth > 0.0) {
      float stepSize = depth * 2.0 / 10.0;
      float extinction = depth < 0.10 ? 8.0 : 3.8;
      // Ten samples through the actual cross section give soft volume, self-occlusion and overlapping wisps.
      for (int i = 0; i < 10; i++) {
        float z = depth - (float(i) + 0.5) * stepSize;
        vec3 q = flowCoordinate(vec3(p, z));
        float warp = noiseAt(q * 0.26 + vec3(0.0, uTime * 0.025, 0.0));
        q.yz += vec2(warp - 0.5, noiseAt(q * 0.33 + 0.37) - 0.5) * 0.48;
        float body = noiseAt(q * 0.38);
        float detail = noiseAt(q * 1.05 + warp * 0.12);
        float density = smoothstep(0.26, 0.73, body * 0.78 + detail * 0.22);
        density = (0.10 + density * 1.85) * smoothstep(0.0, 0.018, depth);
        float alpha = 1.0 - exp(-density * stepSize * extinction);
        float scattering = 0.46 + body * 0.47 + (z / max(depth, 0.001)) * 0.07;
        light += transmittance * alpha * scattering;
        transmittance *= 1.0 - alpha;
      }
    }
    float volumeAlpha = 1.0 - transmittance;
    float alpha = volumeAlpha + plume * (1.0 - volumeAlpha);
    float luminance = (light + plume * 0.82 * (1.0 - volumeAlpha)) / max(alpha, 0.001);
    // The gas fills behind the pen and recedes with the eraser; its volume and advection stay unchanged.
    float pen = mix(${(-WORLD_W / 2 - 0.3).toFixed(4)}, ${(WORLD_W / 2 + 0.3).toFixed(4)}, uInk);
    alpha *= (1.0 - smoothstep(pen - 0.15, pen + 0.15, p.x)) * smoothstep(0.0, 0.03, uInk);
    gasColor = vec4(vec3(luminance), alpha);
  }
`;

// A small, seamless 3D density texture. Generated once; no particle buffers or per-frame CPU simulation.
function makeNoise() {
  const size = 64;
  const data = new Uint8Array(size * size * size);
  const hash = (x: number, y: number, z: number, period: number) => {
    const k = Math.imul(x % period, 73856093) ^ Math.imul(y % period, 19349663) ^ Math.imul(z % period, 83492791);
    return (Math.imul(k ^ (k >>> 13), 1274126177) >>> 0) / 4294967295;
  };
  const smooth = (t: number) => t * t * (3 - 2 * t);
  const mix = (a: number, b: number, t: number) => a + (b - a) * t;
  const noise = (x: number, y: number, z: number, period: number) => {
    const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z);
    const fx = smooth(x - ix), fy = smooth(y - iy), fz = smooth(z - iz);
    return mix(
      mix(mix(hash(ix, iy, iz, period), hash(ix + 1, iy, iz, period), fx), mix(hash(ix, iy + 1, iz, period), hash(ix + 1, iy + 1, iz, period), fx), fy),
      mix(mix(hash(ix, iy, iz + 1, period), hash(ix + 1, iy, iz + 1, period), fx), mix(hash(ix, iy + 1, iz + 1, period), hash(ix + 1, iy + 1, iz + 1, period), fx), fy), fz,
    );
  };
  for (let z = 0; z < size; z++) for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    let value = 0;
    for (let octave = 0; octave < 3; octave++) {
      const period = 4 << octave;
      value += noise(x / size * period, y / size * period, z / size * period, period) * [0.64, 0.26, 0.10][octave];
    }
    data[x + y * size + z * size * size] = Math.round(value * 255);
  }
  const texture = new THREE.Data3DTexture(data, size, size, size);
  texture.format = THREE.RedFormat;
  texture.minFilter = texture.magFilter = THREE.LinearFilter;
  texture.wrapS = texture.wrapT = texture.wrapR = THREE.RepeatWrapping;
  texture.unpackAlignment = 1;
  texture.needsUpdate = true;
  return texture;
}

export default function HeroGas({ still, reveal }: { still?: boolean; reveal?: MutableRefObject<number> }) {
  const noise = useMemo(makeNoise, []);
  const material = useMemo(() => new THREE.ShaderMaterial({
    name: "Steward gas volume",
    glslVersion: THREE.GLSL3,
    vertexShader,
    fragmentShader,
    uniforms: { uNoise: { value: noise }, uTime: { value: 6 }, uInk: { value: 0 } },
    transparent: true,
    depthWrite: false,
    depthTest: false,
    toneMapped: false,
  }), [noise]);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = still ? 6 : clock.elapsedTime;
    material.uniforms.uInk.value = still ? 1 : reveal?.current ?? 1;
  });
  useEffect(() => () => { noise.dispose(); material.dispose(); }, [noise, material]);
  return <mesh position={[0, WORLD_CY, -0.05]} renderOrder={-1} material={material}>
    <planeGeometry args={[WORLD_W, WORLD_H]} />
  </mesh>;
}

