/**
 * Synthetic, labelled defects applied to the gaussians near a pin through the engine's work-buffer
 * modifier (GSplatComponent#setWorkBufferModifier). Nothing here touches the hosted capture: the edit
 * lives in a shader for one page load and every frame rendered with it carries a visible label.
 */
import type { Vec3Tuple } from './types';

export type DefectKind = 'none' | 'leak' | 'corrosion' | 'missing-handwheel';
export const DEFECT_KINDS: DefectKind[] = ['none', 'leak', 'corrosion', 'missing-handwheel'];
export const DEFECT_RADIUS = 0.25;

export function parseDefect(value: string | null | undefined): DefectKind {
  return (DEFECT_KINDS as string[]).includes(value ?? '') ? (value as DefectKind) : 'none';
}

const f = (n: number) => (Number.isFinite(n) ? n : 0).toFixed(5);

const NOISE = /* glsl */ `
float stwHash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.11, 0.17, 0.13));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float stwNoise(vec3 x) {
  vec3 i = floor(x);
  vec3 u = fract(x);
  u = u * u * (3.0 - 2.0 * u);
  return mix(
    mix(mix(stwHash(i), stwHash(i + vec3(1.0, 0.0, 0.0)), u.x), mix(stwHash(i + vec3(0.0, 1.0, 0.0)), stwHash(i + vec3(1.0, 1.0, 0.0)), u.x), u.y),
    mix(mix(stwHash(i + vec3(0.0, 0.0, 1.0)), stwHash(i + vec3(1.0, 0.0, 1.0)), u.x), mix(stwHash(i + vec3(0.0, 1.0, 1.0)), stwHash(i + vec3(1.0, 1.0, 1.0)), u.x), u.y),
    u.z);
}
`;

/** GLSL for the three work-buffer hooks. Centre and radius are baked in as constants. */
export function defectShader(kind: DefectKind, center: Vec3Tuple, radius = DEFECT_RADIUS): string | null {
  if (kind === 'none') return null;
  const head = `
const vec3 STW_C = vec3(${f(center[0])}, ${f(center[1])}, ${f(center[2])});
const float STW_R = ${f(radius)};
${NOISE}
void modifySplatCenter(inout vec3 center) {}
`;
  if (kind === 'missing-handwheel') {
    return `${head}
void modifySplatRotationScale(vec3 originalCenter, vec3 modifiedCenter, inout vec4 rotation, inout vec3 scale) {
  if (distance(originalCenter, STW_C) < STW_R) scale = vec3(0.0);
}
void modifySplatColor(vec3 center, inout vec4 color) {
  if (distance(center, STW_C) < STW_R) color.a = 0.0;
}
`;
  }
  const rotScale = `
void modifySplatRotationScale(vec3 originalCenter, vec3 modifiedCenter, inout vec4 rotation, inout vec3 scale) {}
`;
  if (kind === 'corrosion') {
    return `${head}${rotScale}
void modifySplatColor(vec3 center, inout vec4 color) {
  float d = distance(center, STW_C);
  if (d >= STW_R) return;
  float w = 1.0 - smoothstep(STW_R * 0.55, STW_R, d);
  float n = stwNoise(center * 22.0);
  float m = w * smoothstep(0.25, 0.6, n * 0.7 + stwNoise(center * 55.0) * 0.3 + 0.15);
  float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));
  vec3 rust = mix(vec3(0.33, 0.12, 0.04), vec3(0.66, 0.31, 0.11), stwNoise(center * 70.0));
  color.rgb = mix(color.rgb, rust * (0.55 + 0.7 * luma), clamp(m, 0.0, 1.0));
}
`;
  }
  // leak: dark wet patch, stretched downwards like a drip
  return `${head}${rotScale}
void modifySplatColor(vec3 center, inout vec4 color) {
  vec3 q = center - STW_C;
  q.y = q.y > 0.0 ? q.y * 2.2 : q.y * 0.55;
  float d = length(q);
  if (d >= STW_R) return;
  float w = 1.0 - smoothstep(STW_R * 0.45, STW_R, d);
  float n = stwNoise(center * 30.0);
  float m = clamp(w * (0.75 + 0.25 * n), 0.0, 1.0);
  color.rgb = mix(color.rgb, color.rgb * vec3(0.22, 0.24, 0.27), m);
}
`;
}
