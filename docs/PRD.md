# RevenueRecover AI — Product Requirements Document

**Status:** Pre-implementation (setup complete)
**Track:** AI Revenue Recovery (Track 03) — "Find revenue that's slipping away and win it back"
**Last updated:** 2026-09-01

> This is the living PRD. It is the source of truth for scope, architecture
> decisions, and build status. Update the Status Tracker and Decision Log as
> the build progresses.

---

## 1. Product Summary

RevenueRecover AI is a revenue operations application that detects revenue at
risk, diagnoses the root cause, selects a recovery intervention, executes a
bounded recovery workflow, and measures the money actually recovered.

The core loop is:

```
DETECT → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER
```

**This is not a chatbot.** The AI agent is embedded as the decision layer inside
a real recovery workflow. Its output is a structured decision that the backend
validates and executes, never free-form chat.

### The bar (from the track brief)

> Don't just identify the problem. Show measured money recovered across a batch,
> with compliant escalation, stopping rules, and an audit trail.

---

## 2. Scope

### Revenue-risk scenarios

| # | Scenario | MVP depth |
|---|---|---|
| 1 | **Failed payment** | **Fully functional — the primary workflow** |
| 2 | Checkout abandonment | Architecturally supported, secondary |
| 3 | Failed subscription | Architecturally supported, secondary |
| 4 | Overdue B2B invoice | Architecturally supported, secondary |

**Scope principle:** make scenario 1 excellent rather than making all four
shallow. The data model, risk engine, and agent interfaces must accommodate all
four from day one so the others are additive, not a rewrite.

### Out of scope

Kafka, Kubernetes, microservices, message queues, or any infrastructure beyond
a single API server, a single database, and a Next.js frontend.

---

## 3. Primary User Flow

A payment event enters the system:

```
Customer:                 Rahul Sharma
Amount:                   ₹2,999
Payment status:           Failed
Failure reason:           expired_card
Subscription:             Active
Previous failed attempts: 1
Customer lifetime value:  ₹25,000
```

The system then:

1. Detects that revenue is at risk
2. Creates a recovery case
3. Calculates a revenue-risk score (deterministic, pre-AI)
4. Diagnoses the likely root cause (AI)
5. Selects the best recovery intervention (AI)
6. Validates that intervention against policy limits (backend, authoritative)
7. Executes the approved action using controlled tools
8. Waits for / simulates the resulting payment event
9. Determines whether the payment was recovered
10. Updates recovered revenue
11. Records every step in an audit trail

---

## 4. Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ Next.js frontend (App Router, TypeScript, Tailwind, Recharts) │
└───────────────────────────┬───────────────────────────────────┘
                            │  REST (JSON)
┌───────────────────────────▼───────────────────────────────────┐
│  FastAPI backend                                              │
│                                                               │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Risk Engine│→ │ Recovery     │→ │ AI Recovery Agent    │   │
│  │(rule-based)│  │ Workflow     │  │ (structured decision)│   │
│  └────────────┘  └──────┬───────┘  └──────────────────────┘   │
│                         │                                     │
│                  ┌──────▼────────┐                            │
│                  │ Policy Guard  │  ← authoritative limits    │
│                  └──────┬────────┘                            │
│         ┌───────────────┼───────────────┐                     │
│  ┌──────▼─────┐ ┌───────▼──────┐ ┌──────▼──────┐              │
│  │  Payment   │ │ Notification │ │  Analytics  │              │
│  │  Service   │ │   Service    │ │   Service   │              │
│  └────────────┘ └──────────────┘ └─────────────┘              │
└───────────────────────────┬───────────────────────────────────┘
                            │
                   ┌────────▼─────────┐
                   │   PostgreSQL     │
                   └──────────────────┘
```

### Module boundaries

Each is a separate logical module under `backend/app/`:

| Module | Responsibility |
|---|---|
| `risk/` | Deterministic risk scoring; `RiskEngine` interface |
| `agents/` | AI decision layer + provider abstraction |
| `workflow/` | Recovery state machine; orchestrates the six phases |
| `services/` | Payment, Notification, Analytics services |
| `simulations/` | Payment event simulator, demo seeding |
| `models/` | SQLAlchemy ORM models |
| `database/` | Session management, migrations |
| `api/` | FastAPI routers — thin, no business logic |

**Rule:** all business logic lives on the backend. The frontend renders state
and calls REST endpoints; it never computes money, risk, or eligibility.

---

## 5. Revenue Risk Engine

A **deterministic, rule-based** scoring engine that runs *before* the AI layer.

> **Honesty requirement:** the risk score is rule-based and must be labelled as
> such in the UI. Do not present it as AI-generated.

### Scoring factors

- Transaction amount
- Customer lifetime value
- Active subscription status
- Number of previous payment failures
- Days until subscription cancellation
- Payment failure type
- Customer history

Output: an integer **0–100**, plus the itemised factor contributions that
produced it (both are surfaced in the UI).

### Risk bands

| Score | Level |
|---|---|
| 0–30 | Low |
| 31–60 | Medium |
| 61–80 | High |
| 81–100 | Critical |

### Extensibility

```
RiskEngine (interface)
  ├── RuleBasedRiskEngine   ← MVP, always available
  └── MLRiskEngine          ← optional, trained on historical/Kaggle data
```

The MVP must work fully without the ML model.

---

## 6. AI Recovery Agent

### Provider

Claude API (`claude-opus-5`) via the official `anthropic` Python SDK, behind a
provider interface so it can be swapped. A deterministic `rules` provider is
included as a fallback so the entire demo runs without an API key.

### Decision contract

The agent receives structured case context and returns a validated decision:

```json
{
  "diagnosis": "expired_card",
  "confidence": 0.94,
  "recommended_action": "generate_payment_link",
  "reason": "Retrying an expired card is unlikely to succeed. The customer should update their payment method.",
  "escalation_required": false
}
```

Enforced via structured outputs / strict tool schemas — the decision is
schema-validated before it reaches the workflow. Malformed decisions are
rejected, not coerced.

### Controlled tools

The agent has **no unrestricted database access.** It sees only these tools:

**Read-only investigation tools** (agent may call directly):

| Tool | Purpose |
|---|---|
| `get_customer()` | Customer profile and LTV |
| `get_transaction()` | The failed transaction |
| `get_payment_history()` | Prior payment attempts |
| `check_payment_status()` | Current status of a payment |

**Action tools** (agent *selects*; the backend *executes* after validation):

| Tool | Purpose |
|---|---|
| `retry_payment()` | Re-attempt the charge |
| `generate_payment_link()` | Payment-method update link |
| `send_email()` | Email the customer |
| `send_whatsapp()` | WhatsApp the customer |
| `schedule_retry()` | Defer a retry |
| `escalate_to_human()` | Hand off to a human |
| `mark_case_resolved()` | Close the case |

This split is what makes the workflow bounded: the AI never directly performs a
side effect on money or on a customer's inbox.

### Chain-of-thought policy

Hidden reasoning is never exposed. The UI shows only concise, user-facing
explanations ("Retry is unlikely to succeed.").

---

## 7. Recovery Decision Logic

| Condition | Strategy |
|---|---|
| `expired_card` | Generate payment update link → send payment update email |
| `temporary_bank_failure` | Schedule retry |
| `insufficient_funds` | Schedule retry later → send appropriate reminder |
| `multiple_failed_attempts` | Limit retries; escalate once retry limit reached |
| High-value customer | Prefer careful intervention; escalate when appropriate |
| Checkout abandonment | Send recovery reminder |
| Overdue invoice | Reminder sequence; escalate past overdue threshold |

---

## 8. Bounded Workflow & Safety — *critical requirement*

The agent proposes; **the backend disposes.** Every limit below is enforced in
backend code and holds even when the AI recommends otherwise.

| Limit | Default | Config key |
|---|---|---|
| Maximum payment retries | 2 | `MAX_PAYMENT_RETRIES` |
| Maximum reminders | 3 | `MAX_REMINDERS` |
| Customer contact cooldown | 24 hours | `CONTACT_COOLDOWN_HOURS` |
| Escalation amount threshold | ₹50,000 | `ESCALATION_AMOUNT_THRESHOLD` |
| High-value LTV threshold | ₹50,000 | `HIGH_VALUE_LTV_THRESHOLD` |

Additional invariants:

- Recovery stops once the retry limit is reached
- The same failing action is not retried repeatedly
- Every automated action is logged to `agent_actions`
- Human escalation is always available
- Every recovery case has a complete audit trail

**Acceptance:** an AI decision that violates a limit must be *blocked and
logged*, not silently executed. This path needs an explicit test.

---

## 9. Payment Simulation

A payment event simulator drives the demo with no external dependency. A demo
user can create a successful or failed payment, choosing:

- Customer
- Transaction amount
- Failure reason
- Scenario type

and then trigger the recovery workflow. The visible sequence:

```
Payment Failed → Revenue Risk Detected → Risk Score Calculated
→ AI Diagnosis → AI Decision → Payment Link Generated → Email Sent
→ Customer Pays → Payment Successful → ₹2,999 Recovered
```

---

## 10. Data Model

All money is stored in **paise (integer)** to avoid floating-point drift, and
formatted as INR at the presentation layer.

### `customers`
`id`, `name`, `email`, `phone`, `lifetime_value`, `subscription_status`, `created_at`

### `transactions`
`id`, `customer_id`, `amount`, `currency`, `status`, `failure_reason`, `created_at`

### `recovery_cases`
`id`, `transaction_id`, `risk_score`, `risk_level`, `diagnosis`, `confidence`,
`recommended_action`, `action_taken`, `status`, `amount_at_risk`,
`amount_recovered`, `created_at`, `resolved_at`

### `agent_actions`
`id`, `recovery_case_id`, `action_type`, `reasoning`, `status`, `timestamp`

### `messages`
`id`, `recovery_case_id`, `channel`, `recipient`, `message`, `status`, `timestamp`

---

## 11. Historical Data Ingestion

Support importing a historical transaction CSV (e.g. from Kaggle) through a
**configurable column-mapping layer** — the system must not be coupled to any
single dataset's column names.

Historical data is used for: customer behaviour analysis, failure-pattern
analysis, risk-model experimentation, and dashboard analytics.

The real-time recovery workflow operates on newly generated payment events,
independently of the static historical dataset.

---

## 12. API Surface

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/dashboard` | KPI cards + headline metrics |
| GET | `/api/customers` | Customer list |
| GET | `/api/transactions` | Transaction list |
| GET | `/api/recovery-cases` | Case list (filterable) |
| GET | `/api/recovery-cases/{id}` | Case detail + audit trail |
| POST | `/api/payments/simulate` | Create a simulated payment event |
| POST | `/api/recovery-cases/{id}/run-agent` | Run the AI decision layer |
| POST | `/api/recovery-cases/{id}/execute` | Execute the approved action |
| POST | `/api/recovery-cases/{id}/simulate-payment` | Simulate customer payment |
| GET | `/api/agent/actions` | Agent activity feed |
| GET | `/api/analytics` | Time series + breakdowns |

---

## 13. Frontend

### Navigation

Dashboard · Recovery Cases · Customers · Transactions · Agent Activity ·
Analytics · Settings

Plus: home button, search, notifications, user profile.

### Dashboard

**Money is the most important metric.** Top KPI cards:

| Card | Example |
|---|---|
| Revenue At Risk | ₹4,82,500 |
| Revenue Recovered | ₹3,17,400 |
| Recovery Rate | 65.8% |
| Active Recovery Cases | 27 |

Analytics: revenue at risk over time, revenue recovered over time, recovery
rate, failed payments by reason, recovery actions by type, successful vs.
unsuccessful interventions.

### Recovery Cases page

Columns: Customer · Amount · Risk · Problem · AI Action · Status · Created ·
Recovered. Filterable by status, risk level, recovery type, date, amount.

### Recovery Case detail

Shows the six phases (Detected → Diagnosis → Decision → Action → Result) with
confidence, plus a chronological audit trail with timestamps.

### Agent Activity panel

Displays the current workflow state:

```
DETECTING → DIAGNOSING → DECIDING → EXECUTING → VERIFYING → RECOVERED
```

Concise user-facing explanations only — never hidden reasoning.

### Design direction

Minimalistic, professional, highly usable — a serious revenue operations
product. Dark/neutral premium interface, clean typography, strong hierarchy,
generous whitespace, subtle borders, minimal gradients.

**Avoid:** glassmorphism, excessive animation, generic AI/robot graphics,
clutter.

Colour is restrained and reserved for risk levels, success/failure states, and
financial metrics. **₹ recovered is the most visually prominent number.**
INR formatting throughout. Fully responsive.

---

## 14. Demo Mode

Critically important — the whole workflow must be demonstrable with no external
dependencies. Seeded demo customers and transactions, plus:

- `Simulate Failed Payment`
- `Simulate Checkout Abandonment`
- `Simulate Recovery`
- `Reset Demo Data`

Events must be realistic and the dashboard must update immediately.

**Target: full end-to-end demo in under 2 minutes.**

---

## 15. Engineering Rules

1. No fake UI without working backend logic
2. No hardcoded dashboard numbers
3. Dashboard metrics computed from database data
4. Recovery status genuinely changes after simulated actions
5. Agent actions create real `agent_actions` records
6. Every recovery case has an audit trail
7. AI decisions are structured and validated
8. Backend enforces limits even when the AI suggests otherwise
9. AI provider logic stays modular and swappable
10. API keys and DB credentials come from environment variables
11. Seed data included
12. README with setup instructions
13. Database migrations / schema included
14. Loading, error, empty and success states all handled
15. Responsive
16. No over-engineered infrastructure

---

## 16. Build Phases

Build in incremental *working* stages — no placeholder screens.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Prerequisites verified, env/infra config committed | ✅ Complete |
| 1 | Database schema + models + seed data | ⬜ Not started |
| 2 | Payment simulation + recovery case creation | ⬜ Not started |
| 3 | Risk engine | ⬜ Not started |
| 4 | AI recovery agent (structured decisions) | ⬜ Not started |
| 5 | Policy guard + recovery action execution | ⬜ Not started |
| 6 | REST API surface | ⬜ Not started |
| 7 | Dashboard + cases + case detail | ⬜ Not started |
| 8 | Analytics + agent activity | ⬜ Not started |
| 9 | Historical CSV ingestion | ⬜ Not started |
| 10 | UI polish + responsiveness | ⬜ Not started |

---

## 17. Acceptance Criteria

The project is complete only when this scenario works end to end:

- [ ] 1. A payment failure is generated
- [ ] 2. A recovery case is automatically created
- [ ] 3. Revenue-at-risk is calculated
- [ ] 4. Risk score is displayed
- [ ] 5. AI diagnoses the failure
- [ ] 6. AI chooses an intervention
- [ ] 7. Backend validates the intervention against safety limits
- [ ] 8. The action is executed
- [ ] 9. Audit trail is created
- [ ] 10. Customer payment can be simulated
- [ ] 11. Case changes to RECOVERED
- [ ] 12. Recovered revenue increases
- [ ] 13. Dashboard metrics update
- [ ] 14. Analytics reflect the recovery
- [ ] 15. The whole workflow demos in under 2 minutes

---

## 18. Decision Log

| # | Decision | Rationale |
|---|---|---|
| D1 | Money stored as integer paise | Avoids floating-point drift in financial totals; formatted to INR at the edge |
| D2 | Postgres on host port **5433** | Avoids collision with any local Postgres already on 5432 |
| D3 | SQLite fallback via `DATABASE_URL` | Postgres is the target, but the demo must run with zero infrastructure. ORM stays DB-agnostic — no Postgres-only column types |
| D4 | AI decision via **structured outputs**, not free text | Decisions are schema-validated before they reach the workflow; malformed output is rejected |
| D5 | Read-only tools exposed to the AI; write actions executed by the backend | Implements the "AI proposes, backend disposes" boundary that makes the workflow bounded |
| D6 | `rules` provider as an AI fallback | The demo must never fail because of a missing API key or network outage |
| D7 | Risk engine is deterministic and labelled rule-based | The PRD explicitly forbids presenting rule-based scoring as AI |
| D8 | Model `claude-opus-5` | Current-generation default; structured outputs + tool calling |

---

## 19. Open Questions

| # | Question | Status |
|---|---|---|
| Q1 | Is an `ANTHROPIC_API_KEY` available for the demo, or should it run on the `rules` provider? | Open — `rules` fallback covers either answer |
| Q2 | Should Docker/Postgres be required for the demo, or is the SQLite path preferred for judging? | Open — both supported |
| Q3 | Which Kaggle dataset (if any) will be used for historical analytics? | Open — mapping layer makes this deferrable |

---

## 20. Environment — verified during setup

| Component | Version | Notes |
|---|---|---|
| Node | 24.13.0 | |
| npm | 11.6.2 | |
| Python | 3.14.0 | All backend deps verified installing cleanly |
| Docker | 29.6.1 | Desktop daemon must be started before `docker compose up` |
| PostgreSQL | 16-alpine | Via `docker-compose.yml`, host port 5433 |

Version numbers above were confirmed by installing and running each toolchain.
The Python dependency set in `backend/requirements.txt` was installed
successfully on Python 3.14 before being pinned. The Postgres image pull was
interrupted by a network error and has not yet been completed — run
`docker compose up -d` once to finish it.

No application code exists yet by design: this repository intentionally holds
only the specification and the prerequisites, so implementation starts from a
clean Phase 1.
