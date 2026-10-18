import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ConversationsPage from "@/components/dash3/conversations";
import { isSite3 } from "@/lib/sites-3";

/* The environment's own Conversations page (owner, Oct 18): the same page as /app/conversations, showing only this site. */
export const metadata: Metadata = { title: "Conversations" };
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <ConversationsPage siteId={site} />;
}
