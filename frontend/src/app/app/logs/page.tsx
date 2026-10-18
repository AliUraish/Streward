import { redirect } from "next/navigation";

/* What happened last is on the overview (and on each environment's page). */
export default function Page() { redirect("/app#logs"); }
