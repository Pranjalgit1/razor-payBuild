import { Activity, CircleDollarSign, IndianRupee, Target } from "lucide-react";
import Link from "next/link";

import { CaseTable } from "@/components/case-table";
import { DemoResetButton } from "@/components/demo-reset-button";
import { KpiCard } from "@/components/kpi-card";
import { apiRequest } from "@/lib/api/client";
import type { Dashboard } from "@/lib/api/types";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const dashboard = await apiRequest<Dashboard>("/api/dashboard");

  return (
    <main className="page-stack">
      <header className="page-header">
        <div><p className="eyebrow">Revenue operations</p><h1>Recovery overview</h1><p className="page-subtitle">Verified money movement and active recovery work from the live database.</p></div>
        <div className="header-actions"><DemoResetButton /><Link className="button primary" href="/simulate">Simulate payment</Link></div>
      </header>

      <section className="kpi-grid" aria-label="Recovery metrics">
        <KpiCard label="Revenue recovered" value={dashboard.revenue_recovered_formatted} note={`${dashboard.recovered_cases} fully recovered cases`} icon={IndianRupee} prominent />
        <KpiCard label="Revenue at risk" value={dashboard.revenue_at_risk_formatted} note="Outstanding on active and escalated cases" icon={CircleDollarSign} />
        <KpiCard label="Recovery rate" value={`${dashboard.recovery_rate.toFixed(1)}%`} note="Verified recovery ÷ total case value" icon={Target} />
        <KpiCard label="Active cases" value={String(dashboard.active_recovery_cases)} note={`${dashboard.total_recovery_cases} cases created overall`} icon={Activity} />
      </section>

      <section className="section-stack">
        <div className="section-heading"><div><p className="eyebrow">Newest workflow entries</p><h2>Recent recovery cases</h2></div><Link className="text-link" href="/recovery-cases">View all cases</Link></div>
        <CaseTable cases={dashboard.recent_cases} />
      </section>
    </main>
  );
}
