import TeamPage from "@/components/dash3/team";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Team");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <TeamPage siteId={site as SiteId3} />;
}
