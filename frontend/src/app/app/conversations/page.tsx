import type { Metadata } from "next";
import ConversationsPage from "@/components/dash3/conversations";

export const metadata: Metadata = { title: "Conversations" };
export default function Page() { return <ConversationsPage />; }
