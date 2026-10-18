import type { Metadata } from "next";
import { site3 } from "@/lib/sites-3";

/* Page titles for the factory pages: "<page> · <factory>". */
export const siteMeta = (page: string | null) => async ({ params }: { params: Promise<{ site: string }> }): Promise<Metadata> => {
  const { site } = await params;
  return { title: page ? `${page} · ${site3(site).name}` : site3(site).name };
};
