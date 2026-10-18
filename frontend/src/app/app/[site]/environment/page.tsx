import EnvironmentPage from "@/components/dash3/environment";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Environment");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <EnvironmentPage siteId={site as SiteId3} />;
}
