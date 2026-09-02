import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/badge";
import type { RecoveryCaseListItem } from "@/lib/api/types";
import { formatDate, humanize, riskTone, statusTone } from "@/lib/labels";

export function CaseTable({ cases }: { cases: RecoveryCaseListItem[] }) {
  if (!cases.length) {
    return <div className="panel empty-state"><div><h3>No recovery cases yet</h3><p>Simulate a failed payment to create the first persisted case.</p><Link className="button primary" href="/simulate">Open simulator</Link></div></div>;
  }

  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Customer</th><th>Amount</th><th>Risk</th><th>Problem</th><th>AI action</th><th>Status</th><th>Created</th><th aria-label="Open" /></tr></thead>
        <tbody>
          {cases.map((item) => (
            <tr key={item.id}>
              <td><strong>{item.customer.name}</strong><small>Case #{item.id}</small></td>
              <td><strong>{item.amount_at_risk_formatted}</strong><small>{item.amount_recovered_formatted} recovered</small></td>
              <td><Badge tone={riskTone(item.risk_level)}>{item.risk_level ? humanize(item.risk_level) : "Unscored"}{item.risk_score !== null ? ` · ${item.risk_score}` : ""}</Badge></td>
              <td>{humanize(item.failure_reason ?? item.diagnosis ?? item.case_type)}</td>
              <td>{humanize(item.recommended_action)}</td>
              <td><Badge tone={statusTone(item.status)}>{humanize(item.status)}</Badge></td>
              <td>{formatDate(item.created_at)}</td>
              <td><Link className="icon-link" href={`/recovery-cases/${item.id}`} aria-label={`Open case ${item.id}`}><ArrowUpRight size={17} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
