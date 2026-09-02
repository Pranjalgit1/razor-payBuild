import { PaymentSimulationForm } from "@/components/payment-simulation-form";
import { apiRequest } from "@/lib/api/client";
import type { Customer, Page } from "@/lib/api/types";

export const dynamic = "force-dynamic";

export default async function SimulatePage() {
  const customers = await apiRequest<Page<Customer>>("/api/customers?limit=200");
  return <main className="page-stack"><header className="page-header"><div><p className="eyebrow">Demo control</p><h1>Simulate a payment event</h1><p className="page-subtitle">Create a real transaction and send failures through detection and deterministic risk scoring.</p></div></header><PaymentSimulationForm customers={customers.items} /></main>;
}
