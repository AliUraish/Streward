import type { Metadata } from "next";
import { notFound } from "next/navigation";
import MemoryPage from "@/components/dash3/memory";
import { isSite3 } from "@/lib/sites-3";

/* The environment's own Memory page (owner, Oct 18): the same page as /app/memory, showing only this site. */
export const metadata: Metadata = { title: "Memory" };
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <MemoryPage siteId={site} />;
}
