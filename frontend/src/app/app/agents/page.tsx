import type { Metadata } from "next";
import AgentMapPage from "@/components/dash3/agent-map";

export const metadata: Metadata = { title: "Agents map" };
export default function Page() { return <AgentMapPage />; }
