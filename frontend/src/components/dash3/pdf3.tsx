"use client";

/* A plain PDF page viewer (pdfjs-dist, worker from public/pdfjs): one page at a time, fit to width, previous and next.
   Used for the cached official regulation PDFs. The page itself is the document, so it stays white. */
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";

export default function Pdf3({ url, title, initialPage = 1 }: { url: string; title: string; initialPage?: number }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [width, setWidth] = useState(560);
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = box.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(e => setWidth(Math.max(240, Math.round(e[0].contentRect.width)))); ro.observe(el); return () => ro.disconnect();
  }, []);
  useEffect(() => {
    let alive = true; let task: PDFDocumentLoadingTask | undefined; const abort = new AbortController();
    setDoc(null); setError(""); setLoading(true); setPage(Math.max(1, initialPage));
    (async () => {
      try {
        const res = await fetch(url, { signal: abort.signal });
        if (res.status === 404 || res.status === 405 || res.status === 501) throw new Error("This PDF is not available yet.");
        if (!res.ok) throw new Error(`The PDF could not be loaded (${res.status}).`);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";
        const bytes = new Uint8Array(await res.arrayBuffer()); if (!alive) return;
        task = pdfjs.getDocument({ data: bytes, useSystemFonts: true, standardFontDataUrl: "/pdfjs/standard_fonts/" });
        const pdf = await task.promise; if (!alive) { await task.destroy(); return; }
        setDoc(pdf); setLoading(false);
      } catch (e) { if (alive && !abort.signal.aborted) { setError(e instanceof Error ? e.message : "The PDF could not be read."); setLoading(false); } }
    })();
    return () => { alive = false; abort.abort(); if (task) void task.destroy(); };
  }, [url, initialPage]);
  useEffect(() => {
    if (!doc || !canvas.current) return;
    let alive = true; let render: RenderTask | undefined;
    (async () => {
      try {
        const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages)); if (!alive || !canvas.current) return;
        const base = p.getViewport({ scale: 1 }); const view = p.getViewport({ scale: width / base.width });
        const ratio = Math.min(window.devicePixelRatio || 1, 2); const c = canvas.current;
        c.width = Math.floor(view.width * ratio); c.height = Math.floor(view.height * ratio); c.style.width = `${view.width}px`; c.style.height = `${view.height}px`;
        const ctx = c.getContext("2d", { alpha: false }); if (!ctx) throw new Error("Canvas rendering is unavailable.");
        render = p.render({ canvas: c, canvasContext: ctx, viewport: view, transform: [ratio, 0, 0, ratio, 0, 0] });
        await render.promise;
      } catch (e) { if (alive && !(e instanceof Error && e.name === "RenderingCancelledException")) setError(e instanceof Error ? e.message : "The page could not be rendered."); }
    })();
    return () => { alive = false; render?.cancel(); };
  }, [doc, page, width]);
  const pages = doc?.numPages ?? 0;
  return <div className="pdf3" aria-label={`${title}, PDF`}>
    <div className="pdf-bar">
      <button type="button" className="b3 quiet small" disabled={!doc || page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}><span>Previous</span></button>
      <span className="pg" aria-live="polite">{doc ? `Page ${page} of ${pages}` : loading ? "Loading the PDF" : ""}</span>
      <button type="button" className="b3 quiet small" disabled={!doc || page >= pages} onClick={() => setPage(p => Math.min(pages, p + 1))}><span>Next</span></button>
    </div>
    <div className="pdf-page" ref={box}>
      {error ? <p className="st3 empty" role="status">{error}</p> : null}
      <canvas ref={canvas} role="img" aria-label={`${title}, page ${page}`} style={{ display: doc && !error ? "block" : "none" }} />
    </div>
  </div>;
}
