import type { Metadata } from "next";
import { notFound } from "next/navigation";
import NotificationsPage from "@/components/dash3/notifications";
import { isSite3 } from "@/lib/sites-3";

/* The environment's own Notifications page (owner, Oct 18): the same page as /app/notifications, showing only this site. */
export const metadata: Metadata = { title: "Notifications" };
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <NotificationsPage siteId={site} />;
}
