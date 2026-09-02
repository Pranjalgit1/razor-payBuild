import { Filter, Plus } from "lucide-react";
import Link from "next/link";

import { CaseTable } from "@/components/case-table";
import { apiRequest } from "@/lib/api/client";
import type { Page, RecoveryCaseListItem } from "@/lib/api/types";
import { humanize } from "@/lib/labels";

export const dynamic = "force-dynamic";

const statuses = ["detected", "decided", "executing", "verifying", "recovered", "escalated", "failed", "abandoned"];
const risks = ["low", "medium", "high", "critical"];
const caseTypes = ["failed_payment", "checkout_abandonment", "failed_subscription", "overdue_invoice"];

type Search = Record<string, string | string[] | undefined>;

function single(value: string | string[] | undefined): string { return Array.isArray(value) ? value[0] ?? "" : value ?? ""; }

export default async function RecoveryCasesPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const offset = Math.max(0, Number(single(search.offset)) || 0);
  const limit = 20;
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  for (const key of ["status", "risk_level", "case_type", "min_amount", "max_amount"]) {
    const value = single(search[key]);
    if (value) query.set(key, value);
  }
  const page = await apiRequest<Page<RecoveryCaseListItem>>(`/api/recovery-cases?${query}`);

  function pageHref(nextOffset: number) {
    const params = new URLSearchParams(query);
    params.set("offset", String(nextOffset));
    return `/recovery-cases?${params}`;
  }

  return (
    <main className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Recovery pipeline</p><h1>Recovery cases</h1><p className="page-subtitle">Filter and inspect every persisted revenue-risk workflow.</p></div><Link className="button primary" href="/simulate"><Plus size={16} />New simulation</Link></header>
      <form className="panel filter-bar" method="GET">
        <span className="filter-title"><Filter size={15} />Filters</span>
        <select aria-label="Status" defaultValue={single(search.status)} name="status"><option value="">All statuses</option>{statuses.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select>
        <select aria-label="Risk" defaultValue={single(search.risk_level)} name="risk_level"><option value="">All risk levels</option>{risks.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select>
        <select aria-label="Case type" defaultValue={single(search.case_type)} name="case_type"><option value="">All case types</option>{caseTypes.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select>
        <input aria-label="Minimum amount in paise" defaultValue={single(search.min_amount)} min="0" name="min_amount" placeholder="Min paise" type="number" />
        <button className="button secondary" type="submit">Apply</button>
        <Link className="text-link" href="/recovery-cases">Clear</Link>
      </form>
      <div className="result-summary"><span>{page.total} cases</span><span>Showing {page.total ? page.offset + 1 : 0}–{Math.min(page.offset + page.limit, page.total)}</span></div>
      <CaseTable cases={page.items} />
      {page.total > limit ? <nav className="pagination" aria-label="Case pages"><Link className={`button secondary${offset === 0 ? " disabled" : ""}`} aria-disabled={offset === 0} href={offset === 0 ? pageHref(0) : pageHref(Math.max(0, offset - limit))}>Previous</Link><span>Page {Math.floor(offset / limit) + 1} of {Math.ceil(page.total / limit)}</span><Link className={`button secondary${offset + limit >= page.total ? " disabled" : ""}`} aria-disabled={offset + limit >= page.total} href={offset + limit >= page.total ? pageHref(offset) : pageHref(offset + limit)}>Next</Link></nav> : null}
    </main>
  );
}
