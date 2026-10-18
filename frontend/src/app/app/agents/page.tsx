import { redirect } from "next/navigation";

/* The agent map is part of the overview's agent mode. */
export default function Page() { redirect("/app?mode=agent"); }
