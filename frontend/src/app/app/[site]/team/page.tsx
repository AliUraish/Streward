import type { Metadata } from "next";
import { notFound } from "next/navigation";
import SitePage from "@/components/dash3/site-page";
import { isSite3 } from "@/lib/sites-3";

/* The environment's Team and chats page (owner, Oct 18: each sidebar option has its own page). */
export const metadata: Metadata = { title: "Team and chats" };
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <SitePage siteId={site} section="team" />;
}
