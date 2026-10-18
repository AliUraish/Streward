"use client";

import { ArrowClockwise, CheckCircle, Circle, SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, type ReactNode } from "react";
import type { Job, Status } from "../../../shared/types";

export const statusLabel: Record<Status, string> = { verified: "Verified", pending: "Pending", issue: "Needs attention", unknown: "Not assessed" };

export function StatusDot({ status, label = false }: { status: Status; label?: boolean }) {
  return <span className={`status-dot-wrap status-${status}`}><span className="status-dot" />{label ? statusLabel[status] : null}</span>;
}

export function StatusBadge({ status }: { status: Status }) {
  const Icon = status === "verified" ? CheckCircle : status === "issue" ? WarningCircle : Circle;
  return <span className={`status-badge status-${status}`}><Icon size={12} weight={status === "verified" ? "fill" : "regular"} />{statusLabel[status]}</span>;
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty-state">{icon ? <div className="empty-icon">{icon}</div> : null}<strong>{title}</strong>{children ? <p>{children}</p> : null}{action}</div>;
}

export function Loading({ label = "Loading workspace" }: { label?: string }) {
  return <div className="loading-state"><SpinnerGap className="spin" size={23} /><span>{label}</span></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error-state" role="alert"><WarningCircle size={24} /><strong>Couldn’t load this view</strong><p>{message}</p>{retry ? <button className="button" onClick={retry}><ArrowClockwise size={14} />Try again</button> : null}</div>;
}

export function ProgressBar({ value }: { value: number }) {
  return <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}

export function JobBanner({ job }: { job: Job | null }) {
  if (!job) return null;
  const working = job.status === "queued" || job.status === "running";
  return <div className={`job-banner job-${job.status}`} role="status">
    {working ? <SpinnerGap className="spin" size={15} /> : job.status === "failed" ? <WarningCircle size={15} /> : <CheckCircle size={15} />}
    <span>{job.message}</span><span className="mono">{Math.round(job.progress)}%</span>{working ? <ProgressBar value={job.progress} /> : null}
  </div>;
}

export function prettyBytes(bytes: number) { return bytes > 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`; }
export function formatTime(value: string) { const d = new Date(value); return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
export function formatDate(value: string) { const d = new Date(value); return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }); }
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : "An unexpected error occurred. Please try again."; }

export function useModal(open: boolean, onClose: () => void) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')).at(-1);
    if (!dialog) return;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]')).filter(element => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close.current(); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) { event.preventDefault(); return; }
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [open]);
}
