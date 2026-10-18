import MetricsPage from "@/components/dash3/metrics";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Metrics");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <MetricsPage siteId={site as SiteId3} />;
}
