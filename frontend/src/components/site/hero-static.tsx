/* The same gas-filled equipment held still for reduced motion or without WebGL. */
import { EDGE_X, GAUGE, PIPE_Y, VOLUTE_R, VOLUTE_Y, WORLD_CY, WORLD_H, WORLD_W, X } from "./story";
import { Draw, GAS_TUBES, TANK, TICKS, WHEEL_Y, buildStatic, needle, tick, wheel } from "./hero-sketch";

function GasStill() {
  return <>
    <defs>
      <clipPath id="steward-gas-interiors">
        {GAS_TUBES.map(({ a, b, r }, i) => <rect key={i}
          x={Math.min(a[0], b[0]) - (a[0] === b[0] ? r : 0)}
          y={-Math.max(a[1], b[1]) - (a[1] === b[1] ? r : 0)}
          width={Math.abs(b[0] - a[0]) || r * 2} height={Math.abs(b[1] - a[1]) || r * 2} />)}
        {[X.p101, X.p102].map(x => <circle key={x} cx={x} cy={-VOLUTE_Y} r={VOLUTE_R - 0.025} />)}
        <rect x={X.tank - TANK.r + 0.025} y={-TANK.top} width={(TANK.r - 0.025) * 2} height={TANK.top - TANK.bottom} />
        {[TANK.top, TANK.bottom].map(y => <circle key={y} cx={X.tank} cy={-y} r={TANK.r - 0.025} />)}
      </clipPath>
      <filter id="steward-gas-density" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.32 1.9" numOctaves={3} seed={7} />
        <feColorMatrix type="matrix" values="0 0 0 0 0.8  0 0 0 0 0.8  0 0 0 0 0.8  0.65 0.65 0.65 0 -0.52" />
      </filter>
    </defs>
    <g clipPath="url(#steward-gas-interiors)">
      <rect x={-WORLD_W / 2} y={-(WORLD_CY + WORLD_H / 2)} width={WORLD_W} height={WORLD_H} fill="white" opacity={0.10} />
      <rect x={-WORLD_W / 2} y={-(WORLD_CY + WORLD_H / 2)} width={WORLD_W} height={WORLD_H} filter="url(#steward-gas-density)" />
    </g>
  </>;
}

export default function HeroStatic({ attestationId }: { attestationId: string }) {
  const d = new Draw();
  d.segs.push(...buildStatic());
  wheel(d, [X.v501, WHEEL_Y]); wheel(d, [X.v504, WHEEL_Y], 0.4);
  needle(d, GAUGE, 2.4);
  for (const c of TICKS) tick(d, c);
  const x0 = -WORLD_W / 2, y0 = -(WORLD_CY + WORLD_H / 2);
  return <div className="static-hero">
    <svg className="plan" viewBox={`${x0} ${y0} ${WORLD_W} ${WORLD_H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Gas fills the Harbor Works pipe network, pump chambers and tank. The pressure gauge reads 2.4 bar and six verification ticks surround P-101.">
      <GasStill />
      <g stroke="#ffffff" strokeWidth={1} vectorEffect="non-scaling-stroke" fill="none" strokeLinecap="round">
        {d.segs.map((s, i) => <line key={i} x1={s[0]} y1={-s[1]} x2={s[2]} y2={-s[3]} vectorEffect="non-scaling-stroke" />)}
      </g>
      <g fill="#ffffff" fontFamily="var(--font-sans)" fontSize={0.3} textAnchor="middle">
        <text x={EDGE_X + 0.25} y={-(PIPE_Y + 0.55)} textAnchor="start">agent · {attestationId}</text>
        <text x={X.p101} y={1.95}>P-101 · 2.4 bar · accepted</text>
        <text x={X.p102} y={1.95}>P-102</text>
        <text x={GAUGE[0] - 0.95} y={-GAUGE[1] + 0.1} textAnchor="end">PG-601</text>
        <text x={X.tank} y={2.55}>TK-201</text>
      </g>
    </svg>
  </div>;
}
