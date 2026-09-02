"use client";

import { Bot, CheckCircle2, Play, RotateCw, ShieldAlert, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/api/client";
import type { AgentRunResponse, RecoveryActionResponse, RecoveryCaseDetail, RecoveryPaymentResponse } from "@/lib/api/types";

const terminalStatuses = new Set(["recovered", "escalated", "failed", "abandoned"]);
const paymentActions = new Set(["retry_payment", "generate_payment_link", "send_email", "send_whatsapp"]);

export function CaseWorkflowActions({ recoveryCase }: { recoveryCase: RecoveryCaseDetail }) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; kind: "success" | "error" } | null>(null);
  const terminal = terminalStatuses.has(recoveryCase.status);
  const canRunAgent = recoveryCase.status === "detected" && recoveryCase.risk_score !== null;
  const scheduledTransition = recoveryCase.recommended_action === "schedule_retry" && recoveryCase.action_taken === "schedule_retry";
  const latestPaymentEvent = [...recoveryCase.actions].reverse().find((action) => action.action_type.startsWith("recovery_payment_"));
  const failedRetry = recoveryCase.action_taken === "retry_payment" && latestPaymentEvent?.action_type === "recovery_payment_failed";
  const canExecute = !terminal && recoveryCase.recommended_action !== null && (
    recoveryCase.action_taken === null
    || (scheduledTransition && recoveryCase.scheduled_retry_due)
    || failedRetry
  );
  const canVerify = !terminal && recoveryCase.action_taken !== null && paymentActions.has(recoveryCase.action_taken) && !failedRetry;

  useEffect(() => {
    if (!scheduledTransition || recoveryCase.scheduled_retry_due || !recoveryCase.scheduled_retry_at) return;
    const remaining = new Date(recoveryCase.scheduled_retry_at).getTime() - Date.now();
    const timer = window.setTimeout(() => router.refresh(), Math.min(Math.max(remaining + 250, 250), 2_147_000_000));
    return () => window.clearTimeout(timer);
  }, [recoveryCase.scheduled_retry_at, recoveryCase.scheduled_retry_due, router, scheduledTransition]);

  async function run<T>(name: string, path: string, body?: unknown) {
    setPending(name);
    setFeedback(null);
    try {
      const result = await apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
      const message = (result as { message?: string }).message ?? "Workflow updated.";
      const rejected = typeof result === "object" && result !== null && "executed" in result && result.executed === false;
      setFeedback({ message, kind: rejected ? "error" : "success" });
      router.refresh();
    } catch (error) {
      setFeedback({ message: error instanceof Error ? error.message : "Request failed.", kind: "error" });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="panel action-panel">
      <div className="section-heading"><div><p className="eyebrow">Controlled workflow</p><h2>Next action</h2></div><span className="policy-note"><ShieldAlert size={14} />Backend policy enforced</span></div>
      <div className="action-grid">
        {canRunAgent ? <button className="button primary" disabled={pending !== null} onClick={() => run<AgentRunResponse>("agent", `/api/recovery-cases/${recoveryCase.id}/run-agent`)}><Bot size={16} />{pending === "agent" ? "Investigating…" : "Run AI agent"}</button> : null}
        {canExecute ? <button className="button primary" disabled={pending !== null} onClick={() => run<RecoveryActionResponse>("execute", `/api/recovery-cases/${recoveryCase.id}/execute`, {})}><Play size={16} />{pending === "execute" ? "Executing…" : failedRetry ? "Review failed retry" : "Execute recommendation"}</button> : null}
        {canVerify ? <button className="button success" disabled={pending !== null} onClick={() => run<RecoveryPaymentResponse>("recover", `/api/recovery-cases/${recoveryCase.id}/simulate-payment`, { succeed: true })}><CheckCircle2 size={16} />{pending === "recover" ? "Verifying…" : "Simulate recovery"}</button> : null}
        {canVerify ? <button className="button secondary" disabled={pending !== null} onClick={() => run<RecoveryPaymentResponse>("fail", `/api/recovery-cases/${recoveryCase.id}/simulate-payment`, { succeed: false, failure_reason: "card_declined" })}><XCircle size={16} />Simulate failed attempt</button> : null}
        {scheduledTransition && !recoveryCase.scheduled_retry_due ? <p className="muted-copy"><RotateCw size={15} />Retry scheduled for {new Date(recoveryCase.scheduled_retry_at ?? "").toLocaleString("en-IN")}. This view will refresh when it becomes due.</p> : null}
        {!terminal && !canRunAgent && !canExecute && !canVerify && !scheduledTransition ? <p className="muted-copy"><RotateCw size={15} />This case is waiting for the next backend-authorized transition.</p> : null}
        {terminal ? <p className="muted-copy">This case is in a terminal or human-review state. Automated controls are disabled.</p> : null}
      </div>
      {feedback ? <p aria-live="polite" className={`feedback ${feedback.kind}`} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.message}</p> : null}
    </section>
  );
}
