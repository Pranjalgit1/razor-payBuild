export type CaseStatus = "detected" | "diagnosed" | "decided" | "executing" | "verifying" | "recovered" | "escalated" | "failed" | "abandoned";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type CaseType = "failed_payment" | "checkout_abandonment" | "failed_subscription" | "overdue_invoice";
export type FailureReason = "expired_card" | "insufficient_funds" | "temporary_bank_failure" | "card_declined" | "network_error" | "authentication_failure" | "invalid_card" | "mandate_revoked" | "checkout_abandoned" | "invoice_overdue";
export type RecoveryAction = "retry_payment" | "generate_payment_link" | "send_email" | "send_whatsapp" | "schedule_retry" | "escalate_to_human" | "mark_case_resolved";
export type ActionStatus = "pending" | "success" | "failed" | "blocked";

export interface Page<T> { items: T[]; total: number; limit: number; offset: number; }

export interface Customer {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  lifetime_value: number;
  lifetime_value_formatted: string;
  subscription_status: string;
  days_until_cancellation: number | null;
  is_business: boolean;
  created_at: string;
}

export interface Transaction {
  id: number;
  customer_id: number;
  amount: number;
  amount_formatted: string;
  currency: string;
  status: string;
  failure_reason: FailureReason | null;
  attempt_number: number;
  parent_transaction_id: number | null;
  is_historical: boolean;
  created_at: string;
}

export interface RiskFactor { label: string; detail: string; points: number; }

export interface AgentAction {
  id: number;
  recovery_case_id: number;
  action_type: string;
  reasoning: string | null;
  status: ActionStatus;
  details: Record<string, unknown> | null;
  timestamp: string;
}

export interface Message {
  id: number;
  recovery_case_id: number;
  channel: string;
  recipient: string;
  subject: string | null;
  message: string;
  status: string;
  timestamp: string;
}

export interface RecoveryCase {
  id: number;
  transaction_id: number;
  customer_id: number;
  case_type: CaseType;
  status: CaseStatus;
  risk_score: number | null;
  risk_level: RiskLevel | null;
  risk_factors: RiskFactor[] | null;
  diagnosis: string | null;
  confidence: number | null;
  recommended_action: RecoveryAction | null;
  decision_reason: string | null;
  escalation_required: boolean;
  action_taken: RecoveryAction | null;
  amount_at_risk: number;
  amount_at_risk_formatted: string;
  amount_recovered: number;
  amount_recovered_formatted: string;
  retry_count: number;
  reminder_count: number;
  last_contact_at: string | null;
  scheduled_retry_at: string | null;
  scheduled_retry_due: boolean;
  created_at: string;
  resolved_at: string | null;
}

export interface RecoveryCaseListItem extends RecoveryCase {
  customer: Customer;
  failure_reason: FailureReason | null;
}

export interface RecoveryCaseDetail extends RecoveryCase {
  customer: Customer;
  transaction: Transaction;
  actions: AgentAction[];
  messages: Message[];
}

export interface Dashboard {
  revenue_at_risk: number;
  revenue_at_risk_formatted: string;
  revenue_recovered: number;
  revenue_recovered_formatted: string;
  recovery_rate: number;
  active_recovery_cases: number;
  total_recovery_cases: number;
  recovered_cases: number;
  recent_cases: RecoveryCaseListItem[];
}

export interface AgentDecision {
  diagnosis: string;
  confidence: number;
  recommended_action: RecoveryAction;
  reason: string;
  escalation_required: boolean;
}

export interface AgentRunResponse {
  case: RecoveryCase;
  decision: AgentDecision;
  metadata: {
    provider: string;
    configured_provider: string;
    model: string | null;
    request_id: string | null;
    fallback_reason: string | null;
    tool_calls: string[];
  };
  audit_actions: AgentAction[];
  idempotent: boolean;
  message: string;
}

export interface RecoveryActionResponse {
  case: RecoveryCase;
  policy: { allowed: boolean; code: string; reason: string; escalation_required: boolean };
  executed: boolean;
  audit_action: AgentAction;
  details: Record<string, unknown>;
  message: string;
}

export interface RecoveryPaymentResponse {
  case: RecoveryCase;
  transaction: Transaction;
  message: string;
}

export interface PaymentSimulationResponse {
  transaction: Transaction;
  recovery_case: RecoveryCase | null;
  message: string;
}

export interface OperationResult { ok: boolean; message: string; detail: Record<string, unknown> | null; }
