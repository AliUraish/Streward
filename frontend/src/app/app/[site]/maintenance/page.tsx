import MaintenancePage from "@/components/dash3/maintenance";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Maintenance");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <MaintenancePage siteId={site as SiteId3} />;
}
