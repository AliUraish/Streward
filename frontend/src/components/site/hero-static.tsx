/* The completed agent workflow, held still for reduced motion or without WebGL. */
import HeroWorkflow from "./hero-workflow";

export default function HeroStatic({ attestationId }: { attestationId: string }) {
  return <HeroWorkflow beat={4} attestationId={attestationId} />;
}
