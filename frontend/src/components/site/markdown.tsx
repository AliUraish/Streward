import type { ReactNode } from "react";

/* A small Markdown renderer for the agent document: headings, paragraphs, lists, blockquotes,
   code fences, inline code, bold, links. Text only; nothing is injected as HTML. */

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0; let m: RegExpExecArray | null; let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) out.push(<code key={`${key}-${i++}`}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) out.push(<strong key={`${key}-${i++}`}>{tok.slice(2, -2)}</strong>);
    else { const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok); if (mm) out.push(<a key={`${key}-${i++}`} href={mm[2]} rel="noreferrer">{mm[1]}</a>); }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(src: string): ReactNode[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let i = 0; let k = 0;
  const key = () => `md-${k++}`;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim(); const buf: string[] = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      nodes.push(<pre key={key()} data-lang={lang || undefined}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { const level = h[1].length; const Tag = (`h${Math.min(level, 4)}`) as "h1" | "h2" | "h3" | "h4"; nodes.push(<Tag key={key()}>{inline(h[2], k)}</Tag>); i++; continue; }
    if (line.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      nodes.push(<blockquote key={key()}><p>{inline(buf.join(" "), k)}</p></blockquote>);
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { let item = lines[i++].replace(/^\s*[-*]\s+/, ""); while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i])) item += " " + lines[i++].trim(); items.push(item); }
      nodes.push(<ul key={key()}>{items.map((it, n) => <li key={n}>{inline(it, k + n)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
      nodes.push(<ol key={key()}>{items.map((it, n) => <li key={n}>{inline(it, k + n)}</li>)}</ol>);
      continue;
    }
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*[-*]\s+|\s*\d+\.\s+)/.test(lines[i])) buf.push(lines[i++]);
    nodes.push(<p key={key()}>{inline(buf.join(" "), k)}</p>);
  }
  return nodes;
}
