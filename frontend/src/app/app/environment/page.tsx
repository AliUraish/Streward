import { redirect } from "next/navigation";

/* The phase-2 route; environments are per factory now. */
export default function Page() { redirect("/app/myer-plant/environment"); }
