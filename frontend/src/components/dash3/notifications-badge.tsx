"use client";

/* The sidebar's count beside Notifications: what arrived since the owner last opened the page (kept on this device).
   On the page itself there is nothing unread, so it shows nothing and does not poll. */
import { usePathname } from "next/navigation";
import { useUnreadNotifications } from "@/lib/hooks-8";
import s from "./notifications.module.css";

export default function NotificationsBadge() {
  const pathname = usePathname() ?? "";
  if (pathname.startsWith("/app/notifications")) return null;
  return <Unread />;
}

function Unread() {
  const n = useUnreadNotifications();
  if (!n) return null;
  const many = n >= 50;
  return <><span className={s.badge} aria-hidden="true">{many ? "50+" : n}</span><span className="sr-only">, {many ? "50 or more" : n} new</span></>;
}
