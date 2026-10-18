import { redirect } from "next/navigation";

/* The phase-2 route; each environment has its own page. */
export default function Page() { redirect("/app/myer-plant"); }
