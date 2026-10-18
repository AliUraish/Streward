import { redirect } from "next/navigation";

/* The phase-2 section route; the dashboard is one page now. */
export default function Page() { redirect("/app#factories"); }
