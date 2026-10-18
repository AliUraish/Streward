import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono"; // taste-skill-ignore: Geist Mono is loaded only for tags, references and hashes
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "Steward",
  description: "Agents ask the plant. The plant answers with proof, or sends someone to get it.",
};
export const viewport: Viewport = { themeColor: "#000000", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // taste-skill-ignore: Geist Mono is loaded for real code and the agent document only
  return <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning><body>{children}<Script id="js-flag" strategy="beforeInteractive">{"document.documentElement.classList.add('js')"}</Script></body>
  </html>;
}
