"use client";

/* The notifications bell at the top right: what arrived since the owner last looked (kept on this device), a short list
   of the latest items, and "See all" to the notifications page. Opening the list marks what it shows as seen. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { markNotificationsSeen, useOwnerNotifications, useUnreadNotifications } from "@/lib/hooks-8";
import { rn, site3 } from "@/lib/sites-3";
import { isSite3 } from "@/lib/sites-3";
import { ago } from "./ui3";

export default function NotificationsBell() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const unread = useUnreadNotifications();
  const onPage = pathname.startsWith("/app/notifications");
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const n = onPage ? 0 : unread;
  return <div className="bell11" ref={ref}>
    <button type="button" className="bell-btn" aria-expanded={open} aria-haspopup="true" aria-label={`Notifications${n ? `, ${n >= 50 ? "50 or more" : n} new` : ""}`} onClick={() => setOpen(o => !o)}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /><path d="M10 20a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
      {n ? <span className="bell-n" aria-hidden="true">{n >= 50 ? "50+" : n}</span> : null}
    </button>
    {open ? <BellList onSeen={markNotificationsSeen} /> : null}
  </div>;
}

function BellList({ onSeen }: { onSeen: (iso: string | null | undefined) => void }) {
  const feed = useOwnerNotifications({ limit: 6 });
  const items = feed.data?.items ?? [];
  useEffect(() => { if (items[0]?.at) onSeen(items[0].at); }, [items, onSeen]);
  return <div className="bell-list" role="dialog" aria-label="Latest notifications">
    <div className="bell-head"><strong>Notifications</strong><Link className="lnk" href="/app/notifications">See all</Link></div>
    {feed.readiness === "loading" && !feed.data ? <p className="bell-note">Loading.</p>
      : !feed.data ? <p className="bell-note">Not available yet.</p>
        : !items.length ? <p className="bell-note">Nothing yet.</p>
          : <ul>{items.map(i => <li key={i.id}><Link href={`/app/notifications?item=${encodeURIComponent(i.id)}`}>
            <span className="bt">{rn(i.title)}</span>
            {i.summary ? <span className="bs">{rn(i.summary)}</span> : null}
            <span className="bm">{i.siteId && isSite3(i.siteId) ? `${site3(i.siteId).short} · ` : ""}{i.mode === "queued" ? "waiting to go out" : ago(i.at)}</span>
          </Link></li>)}</ul>}
  </div>;
}
