import type { Metadata } from "next";
import OverviewPage from "@/components/dash3/overview";

export const metadata: Metadata = { title: "Overview" };
export default function Page() { return <OverviewPage />; }
