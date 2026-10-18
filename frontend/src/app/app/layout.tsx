import type { Metadata } from "next";
import Shell from "@/components/dash3/shell";

export const metadata: Metadata = { title: { default: "Steward dashboard", template: "%s · Steward" }, description: "Three scanned sites, three agent teams, one Operations Director." };

/* The dashboard (REALITY-CONTRACT-4.md section 8): one shell with the sidebar, a page per route. The older views
   (inspection wall, library, agent chat, the Three.js twin) stay on disk in components/ and are not mounted. */
export default function AppLayout({ children }: { children: React.ReactNode }) { return <Shell>{children}</Shell>; }
