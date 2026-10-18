import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import PreviewClient from './preview-client';

export const metadata: Metadata = { title: 'Splat viewer preview', robots: { index: false, follow: false } };

/** Dev-only harness for the splat viewer: `/capture/preview?site=myer-plant|bristol-pumps`. */
export default async function PreviewPage({ searchParams }: { searchParams: Promise<{ [key: string]: string | string[] | undefined }> }) {
  if (process.env.NODE_ENV === 'production') notFound();
  const sp = await searchParams;
  const site = sp.site === 'bristol-pumps' ? 'bristol-pumps' : 'myer-plant';
  return <PreviewClient initialSite={site} />;
}
