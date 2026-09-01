# RevenueRecover AI

An AI revenue recovery agent that detects revenue at risk, diagnoses the cause,
selects a recovery intervention, executes a bounded recovery workflow, and
measures the money actually recovered.

```
DETECT → SCORE → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER
```

Built for the **AI Revenue Recovery** hackathon track.

> **Status: backend Phase 1 and Phase 2 complete.** The database, FastAPI API,
> seed data, payment simulator, automatic recovery-case creation, deterministic
> risk engine, policy guard, controlled actions, payment verification, and audit
> trail are implemented and tested. The AI decision provider and frontend are
> not yet built. See [`docs/PRD.md`](docs/PRD.md) for the full specification.

---

## Repository contents

| Path | Purpose |
|---|---|
| `docs/PRD.md` | Living product requirements document and source of truth |
| `backend/app/models/` | SQLAlchemy models and domain enums |
| `backend/app/risk/` | Deterministic risk-engine contract and rule implementation |
| `backend/app/workflow/` | Policy guard and bounded recovery orchestration |
| `backend/app/services/` | Payment, recovery actions, audit, and formatting services |
| `backend/app/api/routes.py` | Thin REST endpoints |
| `backend/app/simulations/` | Deterministic demo seed data |
| `backend/alembic/` | Database migrations |
| `backend/tests/` | Unit and end-to-end API tests |
| `.env.example` | Environment variable template |
| `docker-compose.yml` | PostgreSQL 16 for local development |

---

## Prerequisites

These versions were verified on Windows 11:

| Tool | Version | Notes |
|---|---|---|
| **Python** | 3.14.0 | Backend dependencies install cleanly |
| **Node.js** | 24.13.0 | Reserved for the Next.js frontend |
| **npm** | 11.6.2 | Ships with Node |
| **Docker** | 29.6.1 | Docker Desktop must be running for PostgreSQL |
| **PostgreSQL** | 16-alpine | Provided by `docker-compose.yml` on host port 5433 |

### Planned stack

- **Frontend** — Next.js, React, TypeScript, Tailwind CSS, Recharts
- **Backend** — Python, FastAPI, SQLAlchemy, Alembic
- **Database** — PostgreSQL, with a zero-infrastructure SQLite fallback
- **AI** — Claude API behind a provider interface, with a deterministic fallback

---

## Setup

### 1. Environment variables

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

- `DATABASE_URL` points at Docker PostgreSQL by default. The included SQLite
  alternative runs the demo without infrastructure.
- `ANTHROPIC_API_KEY` is not needed until the AI decision phase is implemented.

`.env` is ignored by Git; never commit credentials.

### 2. Database

Start Docker Desktop, then:

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

Run this manually in a terminal because the server is long-lived:

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

26 tests cover seed data, historical/live separation, payment simulation,
case creation, deterministic scores and boundaries, audit history, policy
limits, high-value escalation, contact cooldown, durable retry scheduling,
retry reconciliation, successful recovery, terminal safety, and API errors.
They use a temporary SQLite database and require no external services.

### 7. Frontend

Not yet scaffolded; see the remaining phases in the PRD.

---

## Try the complete backend flow

With the API running, first create a failed payment (all amounts are paise):

```powershell
curl.exe -X POST http://localhost:8000/api/payments/simulate `
  -H "Content-Type: application/json" `
  -d '{"customer_id":1,"amount":299900,"succeed":false,"failure_reason":"expired_card"}'
```

The response contains a recovery-case ID, deterministic risk score, risk band,
and seven itemised score factors. Execute a policy-controlled action:

```powershell
curl.exe -X POST http://localhost:8000/api/recovery-cases/1/execute `
  -H "Content-Type: application/json" `
  -d '{"action":"generate_payment_link"}'
```

Then simulate the customer completing payment:

```powershell
curl.exe -X POST http://localhost:8000/api/recovery-cases/1/simulate-payment `
  -H "Content-Type: application/json" `
  -d '{"succeed":true}'
```

Inspect the final state and complete chronological audit trail:

```powershell
curl.exe http://localhost:8000/api/recovery-cases/1
```

High-value cases, exhausted retry/reminder budgets, premature scheduled retries,
contact-cooldown violations, repeated failed actions, and terminal cases are
blocked by backend policy and logged rather than silently executed.

---

## Conventions

- **Money is integer paise.** ₹2,999 is `299900`; response fields also include
  Indian-grouped display strings such as `₹4,82,500`.
- **Risk is deterministic and labelled rule-based.** Seven visible factor
  contributions always add up to the public 0–100 score.
- **The backend is authoritative.** Routers validate and delegate; risk,
  eligibility, limits, money, state transitions, and side effects live in
  backend services and workflows.
- **Actions are bounded.** The backend enforces retry/reminder limits, a
  24-hour contact cooldown, high-value escalation, retryability, terminal-state
  safety, and the rule that a failing action is not repeated.
- **Every outcome is auditable.** Detection, scoring, approvals, blocks,
  execution, escalation, failed payment responses, and verified recovery create
  real `agent_actions` records.
- **Nothing is faked.** AI diagnosis fields remain `null` until the structured
  AI decision phase is implemented.

---

## Next steps

Implement the structured AI recovery agent and rules fallback, then complete the
remaining REST dashboard/analytics endpoints before building the frontend. The
AI will only propose an action; the existing backend policy guard remains the
authority that approves, blocks, or escalates it.
