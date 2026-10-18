import type { Metadata } from "next";
import NotificationsPage from "@/components/dash3/notifications";

export const metadata: Metadata = { title: "Notifications" };
export default function Page() { return <NotificationsPage />; }
