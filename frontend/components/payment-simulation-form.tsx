"use client";

import { FlaskConical } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/api/client";
import type { Customer, FailureReason, PaymentSimulationResponse } from "@/lib/api/types";

const scenarios: { value: FailureReason | "success"; label: string }[] = [
  { value: "expired_card", label: "Failed payment · expired card" },
  { value: "insufficient_funds", label: "Failed payment · insufficient funds" },
  { value: "temporary_bank_failure", label: "Failed payment · temporary bank issue" },
  { value: "checkout_abandoned", label: "Checkout abandonment" },
  { value: "mandate_revoked", label: "Failed subscription mandate" },
  { value: "invoice_overdue", label: "Overdue invoice" },
  { value: "success", label: "Successful payment · no case" },
];

type Feedback = { message: string; kind: "success" | "error" };

export function PaymentSimulationForm({ customers }: { customers: Customer[] }) {
  const router = useRouter();
  const [customerId, setCustomerId] = useState(String(customers[0]?.id ?? ""));
  const [amount, setAmount] = useState("2999");
  const [scenario, setScenario] = useState<FailureReason | "success">("expired_card");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const paise = Math.round(Number(amount) * 100);
    if (!customerId || !Number.isFinite(paise) || paise <= 0) {
      setFeedback({ message: "Choose a customer and enter a positive INR amount.", kind: "error" });
      return;
    }
    setPending(true);
    setFeedback(null);
    try {
      const result = await apiRequest<PaymentSimulationResponse>("/api/payments/simulate", {
        method: "POST",
        body: JSON.stringify({
          customer_id: Number(customerId),
          amount: paise,
          succeed: scenario === "success",
          failure_reason: scenario === "success" ? null : scenario,
        }),
      });
      if (result.recovery_case) {
        router.push(`/recovery-cases/${result.recovery_case.id}`);
      } else {
        setFeedback({ message: result.message, kind: "success" });
        router.refresh();
      }
    } catch (error) {
      setFeedback({
        message: error instanceof Error ? error.message : "Simulation failed.",
        kind: "error",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="panel form-panel" onSubmit={submit}>
      <div className="form-grid">
        <label><span>Customer</span><select value={customerId} onChange={(event) => setCustomerId(event.target.value)} required>{customers.map((customer) => <option value={customer.id} key={customer.id}>{customer.name} · {customer.lifetime_value_formatted} LTV</option>)}</select></label>
        <label><span>Scenario</span><select value={scenario} onChange={(event) => setScenario(event.target.value as FailureReason | "success")}>{scenarios.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
        <label><span>Amount (INR)</span><input inputMode="decimal" min="1" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label>
      </div>
      <div className="form-footer"><p>Failed events create and score a real recovery case immediately.</p><button className="button primary" disabled={pending || !customers.length} type="submit"><FlaskConical size={16} />{pending ? "Simulating…" : "Simulate event"}</button></div>
      {feedback ? <p aria-live="polite" className={`feedback ${feedback.kind}`} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.message}</p> : null}
    </form>
  );
}
