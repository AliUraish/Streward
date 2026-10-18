import type { Metadata } from "next";
import PortfolioPage from "@/components/dash3/portfolio";

export const metadata: Metadata = { title: "Portfolio" };
export default function Page() { return <PortfolioPage />; }
