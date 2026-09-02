import { Badge } from "@/components/badge";
import { apiRequest } from "@/lib/api/client";
import type { AgentAction, Page } from "@/lib/api/types";
import { formatDate, humanize, statusTone } from "@/lib/labels";

export const dynamic = "force-dynamic";

export default async function ActivityPage() {
  const activity = await apiRequest<Page<AgentAction>>("/api/agent/actions?limit=100");
  return <main className="page-stack"><header className="page-header"><div><p className="eyebrow">Audit feed</p><h1>Agent activity</h1><p className="page-subtitle">Chronological backend-owned explanations—never hidden model reasoning.</p></div></header>{activity.items.length ? <section className="panel activity-feed">{activity.items.map((action) => <article key={action.id}><span className={`activity-marker ${statusTone(action.status)}`} /><div><div className="activity-title"><strong>{humanize(action.action_type)}</strong><Badge tone={statusTone(action.status)}>{humanize(action.status)}</Badge></div><p>{action.reasoning ?? "Backend workflow event recorded."}</p><small>Case #{action.recovery_case_id} · {formatDate(action.timestamp, true)}</small></div></article>)}</section> : <section className="panel empty-state">No workflow activity yet. Simulate a failed payment to begin.</section>}</main>;
}
