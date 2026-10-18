import type { Metadata } from "next";
import Dashboard from "@/components/dash3/dashboard";

export const metadata: Metadata = { title: "Steward dashboard", description: "Two scanned factories, six agents, one record." };

/* One page, six sections (REALITY-CONTRACT-3.md section 11). The older views (inspection wall, library, agent chat,
   the Three.js twin) stay on disk in components/ and are no longer mounted. */
export default function AppPage() { return <Dashboard />; }
