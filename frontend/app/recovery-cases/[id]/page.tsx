import { AlertTriangle, ArrowLeft, Bot, CreditCard, History, UserRound } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/badge";
import { CaseWorkflowActions } from "@/components/case-workflow-actions";
import { ApiError, apiRequest } from "@/lib/api/client";
import type { RecoveryCaseDetail } from "@/lib/api/types";
import { formatDate, humanize, riskTone, statusTone } from "@/lib/labels";

export const dynamic = "force-dynamic";

const stages = ["Detected", "Diagnosed", "Decided", "Action", "Verifying", "Recovered"];
const stageByStatus: Record<string, number> = { detected: 0, diagnosed: 1, decided: 2, executing: 3, verifying: 4, recovered: 5, escalated: 3, failed: 4, abandoned: 1 };

export default async function RecoveryCasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let recoveryCase: RecoveryCaseDetail;
  try {
    recoveryCase = await apiRequest<RecoveryCaseDetail>(`/api/recovery-cases/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const currentStage = stageByStatus[recoveryCase.status] ?? 0;

  return (
    <main className="page-stack">
      <Link className="back-link" href="/recovery-cases"><ArrowLeft size={15} />Back to recovery cases</Link>
      <header className="case-hero panel">
        <div><p className="eyebrow">Case #{recoveryCase.id}</p><h1>{recoveryCase.customer.name}</h1><p>{humanize(recoveryCase.transaction.failure_reason ?? recoveryCase.case_type)} · Created {formatDate(recoveryCase.created_at, true)}</p></div>
        <div className="case-hero-money"><span>Revenue at risk</span><strong>{recoveryCase.amount_at_risk_formatted}</strong><small>{recoveryCase.amount_recovered_formatted} verified recovered</small></div>
        <div className="hero-badges"><Badge tone={riskTone(recoveryCase.risk_level)}>{humanize(recoveryCase.risk_level)} risk · {recoveryCase.risk_score ?? "—"}</Badge><Badge tone={statusTone(recoveryCase.status)}>{humanize(recoveryCase.status)}</Badge></div>
      </header>

      <section className="panel workflow-panel"><div className="section-heading"><div><p className="eyebrow">Persisted lifecycle</p><h2>Recovery workflow</h2></div></div><ol className="workflow-steps">{stages.map((stage, index) => <li className={index < currentStage ? "complete" : index === currentStage ? "current" : ""} key={stage}><span>{index + 1}</span><strong>{stage}</strong></li>)}</ol>{recoveryCase.status === "escalated" ? <p className="feedback error"><AlertTriangle size={15} />Automated recovery stopped for human review.</p> : null}</section>

      <div className="detail-grid">
        <section className="panel detail-card"><div className="card-title"><Bot size={17} /><h2>Agent decision</h2></div>{recoveryCase.recommended_action ? <><div className="decision-action">{humanize(recoveryCase.recommended_action)}</div><p>{recoveryCase.decision_reason}</p><dl className="detail-list"><div><dt>Diagnosis</dt><dd>{humanize(recoveryCase.diagnosis)}</dd></div><div><dt>Confidence</dt><dd>{recoveryCase.confidence !== null ? `${Math.round(recoveryCase.confidence * 100)}%` : "—"}</dd></div><div><dt>Executed</dt><dd>{humanize(recoveryCase.action_taken)}</dd></div></dl></> : <div className="compact-empty">No agent decision has been recorded yet.</div>}</section>
        <section className="panel detail-card"><div className="card-title"><CreditCard size={17} /><h2>Payment context</h2></div><dl className="detail-list"><div><dt>Transaction</dt><dd>#{recoveryCase.transaction.id}</dd></div><div><dt>Amount</dt><dd>{recoveryCase.transaction.amount_formatted}</dd></div><div><dt>Failure</dt><dd>{humanize(recoveryCase.transaction.failure_reason)}</dd></div><div><dt>Attempts</dt><dd>{recoveryCase.transaction.attempt_number + recoveryCase.retry_count}</dd></div><div><dt>Scheduled retry</dt><dd>{formatDate(recoveryCase.scheduled_retry_at, true)}</dd></div></dl></section>
        <section className="panel detail-card"><div className="card-title"><UserRound size={17} /><h2>Customer context</h2></div><dl className="detail-list"><div><dt>Customer</dt><dd>{recoveryCase.customer.name}</dd></div><div><dt>Lifetime value</dt><dd>{recoveryCase.customer.lifetime_value_formatted}</dd></div><div><dt>Subscription</dt><dd>{humanize(recoveryCase.customer.subscription_status)}</dd></div><div><dt>Account</dt><dd>{recoveryCase.customer.is_business ? "Business" : "Consumer"}</dd></div></dl></section>
      </div>

      <CaseWorkflowActions recoveryCase={recoveryCase} />

      <div className="detail-grid lower-grid">
        <section className="panel detail-card"><div className="card-title"><AlertTriangle size={17} /><h2>Rule-based risk factors</h2></div>{recoveryCase.risk_factors?.length ? <div className="factor-list">{recoveryCase.risk_factors.map((factor) => <div className="factor" key={`${factor.label}-${factor.points}`}><span><strong>{factor.label}</strong><small>{factor.detail}</small></span><b>+{factor.points}</b></div>)}</div> : <div className="compact-empty">No risk factors recorded.</div>}</section>
        <section className="panel detail-card timeline-card"><div className="card-title"><History size={17} /><h2>Audit timeline</h2></div>{recoveryCase.actions.length ? <ol className="timeline">{recoveryCase.actions.map((action) => <li key={action.id}><span className={`timeline-dot ${statusTone(action.status)}`} /><div><strong>{humanize(action.action_type)}</strong><p>{action.reasoning ?? "Backend event recorded."}</p><small>{formatDate(action.timestamp, true)} · {humanize(action.status)}</small></div></li>)}</ol> : <div className="compact-empty">No audit activity yet.</div>}</section>
      </div>
    </main>
  );
}
