import { notFound } from "next/navigation";
import { SITE3_IDS, isSite3 } from "@/lib/sites-3";

/* Only the three scanned sites exist; anything else under /app/<site> is a 404. The environment page carries its own
   header (the site's name, place and local time). */
export const dynamicParams = false;
export function generateStaticParams() { return SITE3_IDS.map(site => ({ site })); }

export default async function SiteLayout({ children, params }: { children: React.ReactNode; params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!isSite3(site)) notFound();
  return <>{children}</>;
}
