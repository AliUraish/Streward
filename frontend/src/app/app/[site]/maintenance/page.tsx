import { redirect } from "next/navigation";

/* The environment's pages are tabs on its one page now (owner, Oct 18: no sidebar, one page per environment). */
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  redirect(`/app/${site}#maintenance`);
}
