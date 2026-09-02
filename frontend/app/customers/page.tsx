import { Badge } from "@/components/badge";
import { apiRequest } from "@/lib/api/client";
import type { Customer, Page } from "@/lib/api/types";
import { formatDate, humanize } from "@/lib/labels";

export const dynamic = "force-dynamic";

export default async function CustomersPage() {
  const customers = await apiRequest<Page<Customer>>("/api/customers?limit=200");
  return <main className="page-stack"><header className="page-header"><div><p className="eyebrow">Account context</p><h1>Customers</h1><p className="page-subtitle">Seeded and created accounts available to recovery workflows.</p></div></header><div className="panel table-wrap"><table><thead><tr><th>Customer</th><th>Lifetime value</th><th>Subscription</th><th>Type</th><th>Created</th></tr></thead><tbody>{customers.items.map((customer) => <tr key={customer.id}><td><strong>{customer.name}</strong><small>{customer.email}</small></td><td><strong>{customer.lifetime_value_formatted}</strong></td><td><Badge>{humanize(customer.subscription_status)}</Badge></td><td>{customer.is_business ? "Business" : "Consumer"}</td><td>{formatDate(customer.created_at)}</td></tr>)}</tbody></table></div></main>;
}
