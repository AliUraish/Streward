import FactoryOverview from "@/components/dash3/factory-overview";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "./meta";

export const generateMetadata = siteMeta(null);
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <FactoryOverview siteId={site as SiteId3} />;
}
