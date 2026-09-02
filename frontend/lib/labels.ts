import type { CaseStatus, RiskLevel } from "@/lib/api/types";

export function humanize(value: string | null | undefined): string {
  if (!value) return "Not available";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatDate(value: string | null | undefined, includeTime = false): string {
  if (!value) return "—";
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

export function statusTone(status: CaseStatus | string): string {
  if (status === "recovered" || status === "success") return "success";
  if (status === "escalated" || status === "failed" || status === "blocked") return "danger";
  if (status === "verifying" || status === "executing" || status === "pending") return "warning";
  return "neutral";
}

export function riskTone(risk: RiskLevel | null): string {
  if (risk === "critical") return "danger";
  if (risk === "high") return "warning";
  if (risk === "low") return "success";
  return "neutral";
}
