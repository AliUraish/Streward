import type { Metadata } from "next";
import MemoryPage from "@/components/dash3/memory";

export const metadata: Metadata = { title: "Memory" };
export default function Page() { return <MemoryPage />; }
