import ToolsPage from "@/components/dash3/tools";
import type { SiteId3 } from "@/lib/types-3";
import { siteMeta } from "../meta";

export const generateMetadata = siteMeta("Tools");
export default async function Page({ params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  return <ToolsPage siteId={site as SiteId3} />;
}
