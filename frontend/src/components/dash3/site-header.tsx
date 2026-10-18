"use client";

/* The site at the top of every site page: its scan thumbnail, name and place, and the time there, as one link back to
   the site's overview. The overview itself shows the site large, so it has no header. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { SiteTitle } from "./ui3";
import "./dash7.css";

export default function SiteHeader({ siteId }: { siteId: SiteId3 }) {
  const path = usePathname() ?? "";
  const site = site3(siteId);
  const [time, setTime] = useState("");
  useEffect(() => {
    const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: site.tz, hour: "2-digit", minute: "2-digit", hour12: false });
    const tick = () => setTime(fmt.format(new Date()));
    tick(); const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, [site.tz]);
  if (path.replace(/\/+$/, "") === `/app/${siteId}`) return null;
  return <Link className="sitehd7" href={`/app/${siteId}`} data-dissolve="" aria-label={`${site.name}, ${site.place}: site overview`}>
    <img src={site.thumbnailUrl} alt="" width={88} height={50} />
    <span className="sh-say">
      <span className="sh-name"><SiteTitle site={site} /></span>
      <span className="sh-place">{site.place}{time ? ` · ${time} local time` : ""}</span>
    </span>
  </Link>;
}
