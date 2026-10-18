/**
 * Line-of-sight test on the CPU copy of the splat centres (the engine keeps one for its sort), so the
 * capture route can pick an open side of a pin without rendering a probe frame per direction. That
 * matters on SwiftShader, where one frame of the 14 M-gaussian Myer scan takes tens of seconds.
 */
import type { Vec3Tuple } from './types';

export interface SightlineOptions {
  /** Radius of the tube around each sight line, in metres. */
  tube?: number;
  /** Ignore centres this close to the pin (the asset's own surface). */
  nearSkip?: number;
  /** Ignore centres this close to the camera end. */
  camSkip?: number;
}

/**
 * For each camera position, the number of splat centres inside a thin tube between the camera and
 * the pin. All points are in the model frame of the splat (use the entity's inverse world transform).
 */
export function sightlineCounts(centers: Float32Array, pin: Vec3Tuple, cams: Vec3Tuple[], opts: SightlineOptions = {}): number[] {
  const tube = opts.tube ?? 0.06;
  const nearSkip = opts.nearSkip ?? 0.3;
  const camSkip = opts.camSkip ?? 0.05;
  const k = cams.length;
  const ux = new Float64Array(k), uy = new Float64Array(k), uz = new Float64Array(k), len = new Float64Array(k);
  let reach = 0;
  for (let i = 0; i < k; i++) {
    const dx = cams[i][0] - pin[0], dy = cams[i][1] - pin[1], dz = cams[i][2] - pin[2];
    const l = Math.hypot(dx, dy, dz) || 1;
    ux[i] = dx / l; uy[i] = dy / l; uz[i] = dz / l; len[i] = l;
    reach = Math.max(reach, l);
  }
  reach += tube;
  const tube2 = tube * tube;
  const counts = new Array<number>(k).fill(0);
  const [px, py, pz] = pin;
  const n = Math.floor(centers.length / 3);
  for (let j = 0; j < n; j++) {
    const x = centers[j * 3] - px;
    if (x > reach || x < -reach) continue;
    const y = centers[j * 3 + 1] - py;
    if (y > reach || y < -reach) continue;
    const z = centers[j * 3 + 2] - pz;
    if (z > reach || z < -reach) continue;
    const d2 = x * x + y * y + z * z;
    if (d2 > reach * reach || d2 < nearSkip * nearSkip) continue;
    for (let i = 0; i < k; i++) {
      const t = x * ux[i] + y * uy[i] + z * uz[i];
      if (t < nearSkip || t > len[i] - camSkip) continue;
      if (d2 - t * t < tube2) counts[i]++;
    }
  }
  return counts;
}
