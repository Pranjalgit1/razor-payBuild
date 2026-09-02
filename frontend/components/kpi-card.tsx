import type { LucideIcon } from "lucide-react";

export function KpiCard({ label, value, note, icon: Icon, prominent = false }: { label: string; value: string; note: string; icon: LucideIcon; prominent?: boolean }) {
  return (
    <article className={`kpi-card${prominent ? " prominent" : ""}`}>
      <div className="kpi-label"><span>{label}</span><Icon size={17} aria-hidden="true" /></div>
      <strong>{value}</strong>
      <p>{note}</p>
    </article>
  );
}
