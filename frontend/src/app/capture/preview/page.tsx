import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { isSplatSiteId } from '@/components/splat/sites';
import PreviewClient from './preview-client';

export const metadata: Metadata = { title: 'Splat viewer preview', robots: { index: false, follow: false } };

/** Dev-only harness for the splat viewer: `/capture/preview?site=<a SPLAT_SITES id>`. */
export default async function PreviewPage({ searchParams }: { searchParams: Promise<{ [key: string]: string | string[] | undefined }> }) {
  if (process.env.NODE_ENV === 'production') notFound();
  const sp = await searchParams;
  const site = isSplatSiteId(sp.site) ? sp.site : 'myer-plant';
  return <PreviewClient initialSite={site} />;
}
