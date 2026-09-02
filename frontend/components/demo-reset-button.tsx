"use client";

import { RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/api/client";
import type { OperationResult } from "@/lib/api/types";

export function DemoResetButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function resetDemo() {
    if (!window.confirm("Reset all demo cases, actions, and payments to the seeded baseline?")) return;
    setPending(true);
    setMessage(null);
    try {
      const result = await apiRequest<OperationResult>("/api/demo/reset", { method: "POST" });
      setMessage(result.message);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reset failed.");
    } finally {
      setPending(false);
    }
  }

  return <div className="inline-action"><button className="button secondary" disabled={pending} onClick={resetDemo}><RotateCcw size={15} />{pending ? "Resetting…" : "Reset demo"}</button>{message ? <span aria-live="polite" className="action-note" role="status">{message}</span> : null}</div>;
}
