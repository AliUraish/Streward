import { redirect } from "next/navigation";

/* The tools live on the one Tools page for all three sites. */
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  redirect(`/app/tools?siteId=${encodeURIComponent(site)}`);
}
