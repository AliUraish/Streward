import { redirect } from "next/navigation";

/* Agent mode is the one switch at the top now; the overview in agent mode carries the agent view. */
export default function Page() { redirect("/app?mode=agent"); }
