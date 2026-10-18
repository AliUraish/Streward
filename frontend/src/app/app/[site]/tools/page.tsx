import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ToolsPage from "@/components/dash3/tools";
import { isSite3 } from "@/lib/sites-3";

/* The environment's own Tools page (owner, Oct 18): the same page as /app/tools, showing only this site. */
export const metadata: Metadata = { title: "Tools" };
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <ToolsPage siteId={site} />;
}
