import type { Metadata } from "next";
import AgentView from "@/components/dash3/agent-view";

export const metadata: Metadata = { title: "Agent view" };
export default function Page() { return <AgentView />; }
