# RevenueRecover AI

An AI revenue recovery agent that detects revenue at risk, diagnoses the cause,
selects a recovery intervention, executes a bounded recovery workflow, and
measures the money actually recovered.

```
DETECT → SCORE → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER
```

Built for the **AI Revenue Recovery** hackathon track.

> **Status: Phases 1–4 complete (4/5).** The database, FastAPI API,
> deterministic risk and policy layers, structured Claude/Grok agent, verified
> recovery accounting, database-computed dashboard, case workflow UI, payment
> simulator, customer view, and audit activity feed are implemented. The backend
> suite, production frontend build, and an end-to-end KPI smoke flow pass.
> Phase 5 remains for final analytics, polish, and the two-minute demo package.
> See [`docs/PRD.md`](docs/PRD.md).

---

## Repository contents

| Path | Purpose |
|---|---|
| `docs/PRD.md` | Living product requirements document and source of truth |
| `backend/app/models/` | SQLAlchemy models and domain enums |
| `backend/app/risk/` | Deterministic risk-engine contract and rules |
| `backend/app/agents/` | Strict decisions, scoped tools, Claude, Grok, and rules providers |
| `backend/app/workflow/` | Policy guard and bounded recovery orchestration |
| `backend/app/services/` | Agent, payment, action, audit, and formatting services |
| `backend/app/api/routes.py` | Thin REST endpoints |
| `backend/app/simulations/` | Deterministic demo seed data |
| `backend/alembic/` | Database migrations |
| `backend/tests/` | Unit, concurrency, policy, and end-to-end API tests |
| `frontend/` | Next.js dashboard, recovery cases, simulator, customers, and activity UI |
| `.env.example` | Environment variable template |
| `docker-compose.yml` | PostgreSQL 16 for local development |

---

## Prerequisites

These versions were verified on Windows 11:

| Tool | Version | Notes |
|---|---|---|
| **Python** | 3.14.0 | Backend dependencies install cleanly |
| **Node.js** | 24.13.0 | Next.js frontend runtime |
| **npm** | 11.6.2 | Ships with Node |
| **Docker** | 29.6.1 | Docker Desktop must run for PostgreSQL |
| **PostgreSQL** | 16-alpine | `docker-compose.yml`, host port 5433 |

### Stack

- **Frontend** — Next.js 16, React 19, TypeScript, responsive CSS, Lucide icons
- **Backend** — Python, FastAPI, SQLAlchemy, Alembic
- **Database** — PostgreSQL, with a zero-infrastructure SQLite fallback
- **AI** — Grok (`grok-4.6`) or Claude (`claude-opus-5`) behind one provider interface, with deterministic rules fallback

---

## Setup

### 1. Environment variables

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

- `DATABASE_URL` points at Docker PostgreSQL by default. Select the included
  SQLite URL to run without infrastructure.
- For Grok, set `AI_PROVIDER=xai` (the `grok` alias also works) and place a
  newly rotated key in `XAI_API_KEY`. The default model is `grok-4.6`.
- For Claude, set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`; its default
  model is `claude-opus-5`.
- `AGENT_MODEL` is optional and overrides the selected provider's default.
- Missing keys and transient provider outages visibly fall back to the
  deterministic `rules` provider. Set `AI_PROVIDER=rules` to force offline mode.
- Malformed provider decisions are rejected and audited; they do not fall back
  or get coerced into valid decisions.

`.env` is ignored by Git; never commit credentials.

### 2. Database

```powershell
docker compose up -d
docker compose exec postgres pg_isready -U revenue -d revenuerecover
```

SQLite can be used instead by selecting its `DATABASE_URL` in `.env`.

### 3. Backend environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

### 4. Apply migrations and seed

```powershell
Set-Location backend
python -m alembic upgrade head
python manage.py seed
```

### 5. Run the API

Run this manually because the server is long-lived:

```powershell
Set-Location backend
python -m uvicorn app.main:app --reload --port 8000
```

Interactive API docs: <http://localhost:8000/docs>

> Recovery mutation endpoints are intentionally unauthenticated for the local
> hackathon demo. Bind the API to localhost and do not expose it publicly until
> authentication and authorization are added.

### 6. Run the tests

```powershell
Set-Location backend
python -m pytest -v
```

41 tests cover seeding, payment simulation, deterministic risk, strict agent
outputs, bounded live-provider tool calls, provider fallback, read-tool scoping,
concurrent decision idempotency, recommendation execution, policy blocks,
contact cooldown, durable scheduling, retry verification, audit safety, and
recovered-revenue accounting. They use temporary SQLite and need no API key.

### 7. Frontend

Install and configure the public API origin:

```powershell
Set-Location frontend
Copy-Item .env.local.example .env.local
npm install
```

Run the Next.js development server manually because it is long-lived:

```powershell
Set-Location frontend
npm run dev
```

Open <http://localhost:3000>. The UI includes live database-backed KPIs,
filterable recovery cases, full case workflow controls, a payment simulator,
customers, and agent activity. FastAPI must be running on port 8000 unless
`NEXT_PUBLIC_API_BASE_URL` is changed.

---

## Try the complete backend flow

Create a failed payment (all amounts are paise):

```powershell
curl.exe -X POST http://localhost:8000/api/payments/simulate `
  -H "Content-Type: application/json" `
  -d '{"customer_id":1,"amount":299900,"succeed":false,"failure_reason":"expired_card"}'
```

Run the structured agent for the returned recovery-case ID:

```powershell
curl.exe -X POST http://localhost:8000/api/recovery-cases/1/run-agent
```

The agent can call only four case-scoped read tools. It returns a strict
five-field decision; the backend persists DIAGNOSED and DECIDED audit steps but
does not perform the proposed side effect.

Execute the persisted recommendation through the authoritative policy guard:

```powershell
curl.exe -X POST http://localhost:8000/api/recovery-cases/1/execute `
  -H "Content-Type: application/json" `
  -d '{}'
```

Simulate the customer completing payment:

```powershell
curl.exe -X POST http://localhost:8000/api/recovery-cases/1/simulate-payment `
  -H "Content-Type: application/json" `
  -d '{"succeed":true}'
```

Inspect final state and the chronological audit trail:

```powershell
curl.exe http://localhost:8000/api/recovery-cases/1
```

High-value cases, exhausted retry/reminder budgets, premature scheduled retries,
contact-cooldown violations, mismatched recommendations, repeated failed
actions, and terminal cases are blocked and logged rather than silently run.

---

## AI and safety boundaries

- **Strict decisions.** Diagnosis, confidence, one controlled action, public
  reason, and escalation flag are schema-validated without scalar coercion.
- **Read-only investigation.** Providers see only case-scoped customer traits,
  the failed transaction, bounded payment history, and payment status. Contact
  addresses and writable sessions are not exposed to the model.
- **Backend-owned public text.** Provider prose is never persisted; concise
  explanations are generated from validated diagnosis/action enums.
- **Visible fallback.** Responses and audits identify the effective provider,
  configured provider, model, tool calls, and fallback reason.
- **AI proposes; backend disposes.** Every recommendation still passes retry,
  reminder, cooldown, amount, LTV, retryability, schedule, and terminal checks.
- **Concurrent safety.** A compare-and-set claim and SQLite contention retries
  ensure concurrent agent runs persist exactly one decision and audit sequence.

## Conventions

- Money is integer paise; responses include Indian-grouped display strings.
- Risk is deterministic, labelled rule-based, and its factors sum to the score.
- Business logic, state transitions, money, and eligibility live in the backend.
- Every detection, score, diagnosis, decision, approval, block, execution,
  escalation, failure, and verified recovery creates a real audit record.

---

## Next steps

Phase 5 will add database-backed analytics visualizations, complete final visual
polish and accessibility review, and package the end-to-end workflow into a
rehearsed two-minute buildathon demo. No chart will be added until its metrics
are defined and computed by the backend.
