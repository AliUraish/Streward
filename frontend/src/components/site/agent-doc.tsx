"use client";

import { useEffect, useState } from "react";
import { renderMarkdown } from "./markdown";

/* Agent mode: the page as text, with no controls. Fetches /llms.txt at runtime (served by src/app/llms.txt/route.ts
   from docs/llms.txt). The connect snippet is a code block; the only control on the page is the switch in the bar. */
export default function AgentDoc({ mcpUrl }: { mcpUrl: string }) {
  const [md, setMd] = useState<string | null>(null);
  const [error, setError] = useState("");
  const cmd = `claude mcp add --transport http steward ${mcpUrl}`;
  const json = `{\n  "mcpServers": {\n    "steward": { "type": "http", "url": "${mcpUrl}" }\n  }\n}`;

  useEffect(() => {
    let alive = true;
    fetch("/llms.txt", { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(`GET /llms.txt returned ${r.status}`); return r.text(); })
      .then(t => { if (alive) setMd(t); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : "Could not fetch /llms.txt"); });
    return () => { alive = false; };
  }, []);

  return <div className="agent-doc" data-ui="">
    <div className="doc-head">
      <h1>Steward, as text.</h1>
      <p>This is the same page for an agent. Add the MCP and the three verbs are tools.</p>
    </div>
    <section className="connect-block" aria-label="Connect an agent">
      <h2>Connect an agent</h2>
      <pre><code>{cmd}</code></pre>
      <pre><code>{json}</code></pre>
    </section>
    <article className="doc-body" aria-live="polite">
      {md ? renderMarkdown(md) : error ? <p className="doc-error">The guide could not be loaded.</p> : <p className="doc-loading">Loading the guide</p>}
    </article>
  </div>;
}
