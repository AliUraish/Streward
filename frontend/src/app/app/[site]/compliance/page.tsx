import CompliancePage from "@/components/dash3/compliance-page";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Compliance");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <CompliancePage siteId={site as SiteId3} />;
}
