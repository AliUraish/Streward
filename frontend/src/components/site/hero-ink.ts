import * as THREE from "three";

interface Ink {
  source: Float32Array;
  distance: Float32Array;
  total: number;
  tip: number;
  amount: number;
}

/* Keep the original pen strokes. Only the current tip moves; completed strokes use the original vertices. */
export function inkGeometry(source: Float32Array) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(source.slice(), 3).setUsage(THREE.DynamicDrawUsage));
  const count = source.length / 6;
  const distance = new Float32Array(count + 1);
  for (let i = 0; i < count; i++) {
    const at = i * 6;
    distance[i + 1] = distance[i] + Math.hypot(source[at + 3] - source[at], source[at + 4] - source[at + 1], source[at + 5] - source[at + 2]);
  }
  geometry.userData.ink = { source, distance, total: distance[count], tip: -1, amount: -1 } satisfies Ink;
  geometry.setDrawRange(0, 0);
  return geometry;
}

export function drawInk(geometry: THREE.BufferGeometry, progress: number) {
  const ink = geometry.userData.ink as Ink;
  const amount = Math.min(1, Math.max(0, progress));
  if (amount === ink.amount) return;
  ink.amount = amount;
  const position = geometry.getAttribute("position") as THREE.BufferAttribute;
  const points = position.array as Float32Array;
  if (ink.tip >= 0) {
    const at = ink.tip * 6 + 3;
    points[at] = ink.source[at]; points[at + 1] = ink.source[at + 1]; points[at + 2] = ink.source[at + 2];
  }
  const count = ink.source.length / 6;
  const length = amount * ink.total;
  let segment = 0;
  while (segment < count && ink.distance[segment + 1] <= length) segment++;
  ink.tip = segment < count && amount > 0 ? segment : -1;
  if (ink.tip >= 0) {
    const at = segment * 6;
    const fraction = (length - ink.distance[segment]) / Math.max(1e-6, ink.distance[segment + 1] - ink.distance[segment]);
    for (let axis = 0; axis < 3; axis++) points[at + 3 + axis] = ink.source[at + axis] + (ink.source[at + 3 + axis] - ink.source[at + axis]) * fraction;
  }
  geometry.setDrawRange(0, amount === 0 ? 0 : (segment + (ink.tip >= 0 ? 1 : 0)) * 2);
  position.needsUpdate = true;
}
