"use client";

import { Activity, Gauge, ReceiptText, UsersRound, WalletCards } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const navigation = [
  { href: "/", label: "Dashboard", icon: Gauge },
  { href: "/recovery-cases", label: "Recovery cases", icon: WalletCards },
  { href: "/simulate", label: "Simulate", icon: ReceiptText },
  { href: "/customers", label: "Customers", icon: UsersRound },
  { href: "/activity", label: "Agent activity", icon: Activity },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="RevenueRecover home">
          <span className="brand-mark">R</span>
          <span><strong>RevenueRecover</strong><small>AI operations</small></span>
        </Link>
        <nav aria-label="Primary navigation">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === href : pathname.startsWith(href);
            return (
              <Link aria-current={active ? "page" : undefined} aria-label={label} className={`nav-link${active ? " active" : ""}`} href={href} key={href}>
                <Icon size={18} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" />
          <span><strong>Live API mode</strong><small>Persisted backend data</small></span>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar"><span>Revenue intelligence</span><span className="environment-pill">Prototype</span></div>
        {children}
      </div>
    </div>
  );
}
