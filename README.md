# RevenueRecover AI

An AI revenue recovery agent that detects revenue at risk, diagnoses the cause,
selects a recovery intervention, executes a bounded recovery workflow, and
measures the money actually recovered.

```
DETECT → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER
```

Built for the **AI Revenue Recovery** hackathon track.

> **Status: Phase 1–2 complete.** The database, backend API, seed data, payment
> simulator, and automatic recovery-case creation are built and tested. The risk
> engine, AI agent, and frontend are not yet built. See
> [`docs/PRD.md`](docs/PRD.md) for the full specification and build phases.

---

## Repository contents

| Path | Purpose |
|---|---|
| `docs/PRD.md` | The living product requirements document — source of truth |
| `backend/app/models/` | SQLAlchemy models and domain enums |
| `backend/app/services/` | Payment, case detection, audit trail, INR formatting |
| `backend/app/api/routes.py` | REST endpoints |
| `backend/app/simulations/` | Demo seed data |
| `backend/alembic/` | Database migrations |
| `backend/tests/` | End-to-end API flow tests |
| `.env.example` | Environment variable template |
| `docker-compose.yml` | PostgreSQL 16 for local development |
| `.gitignore` | Ignores `.venv/`, `node_modules/`, `.env`, build output |

---

## Prerequisites

These versions were verified working on the development machine (Windows 11):

| Tool | Version | Notes |
|---|---|---|
| **Python** | 3.14.0 | All backend dependencies confirmed installing cleanly |
| **Node.js** | 24.13.0 | For the Next.js frontend |
| **npm** | 11.6.2 | Ships with Node |
| **Docker** | 29.6.1 | Docker Desktop must be **running** before `docker compose up` |
| **PostgreSQL** | 16-alpine | Provided by `docker-compose.yml` — no local install needed |

### Planned stack

- **Frontend** — Next.js (App Router), React, TypeScript, Tailwind CSS, Recharts
- **Backend** — Python, FastAPI, SQLAlchemy, Alembic
- **Database** — PostgreSQL
- **AI** — Claude API (`claude-opus-5`) with structured outputs and tool calling

---

## Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Then edit `.env`. The two settings that matter most:

- `DATABASE_URL` — points at the Docker Postgres by default (host port **5433**,
  chosen to avoid clashing with any local Postgres on 5432). A SQLite fallback
  is included, commented out, so the demo can run with zero infrastructure.
- `ANTHROPIC_API_KEY` — required only when `AI_PROVIDER=anthropic`. Setting
  `AI_PROVIDER=rules` runs the deterministic fallback agent so the full workflow
  demos without an API key.

`.env` is gitignored — never commit it.

### 2. Database

Start Docker Desktop, then:

```bash
docker compose up -d
```

Verify it is accepting connections:

```bash
docker compose exec postgres pg_isready -U revenue -d revenuerecover
```

### 3. Backend environment

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

### 4. Apply migrations and seed

```bash
cd backend
python -m alembic upgrade head
python manage.py seed
```

### 5. Run the API

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Interactive API docs: <http://localhost:8000/docs>

### 6. Run the tests

```bash
cd backend
python -m pytest
```

16 tests cover the full flow: seeding, INR formatting, payment simulation,
automatic case creation, scenario classification, the audit trail, case
filtering, error handling, and demo reset. They run against a temporary SQLite
database and need no external services.

### 7. Frontend

Not yet scaffolded — see Phase 7 in the PRD.

---

## Try the flow

With the server running:

```bash
# Open a recovery case by simulating a failed payment (amounts are in paise)
curl -X POST http://localhost:8000/api/payments/simulate \
  -H "Content-Type: application/json" \
  -d '{"customer_id": 1, "amount": 299900, "succeed": false, "failure_reason": "expired_card"}'

# Inspect the case and its audit trail
curl http://localhost:8000/api/recovery-cases/1
```

A **failed** payment automatically opens a recovery case — that is the DETECT
stage firing, not a separate manual step. A **successful** payment correctly
opens none.

---

## Conventions

- **Money is stored as integer paise** (₹2,999 = `299900`). Integers avoid the
  floating-point drift that would otherwise accumulate in recovered-revenue
  totals. API responses also include a `*_formatted` string using Indian
  lakh/crore grouping (`₹4,82,500`, not `₹482,500`).
- **Business logic lives on the backend.** Routers validate, call a service, and
  shape a response; they contain no business rules.
- **Nothing is faked.** Fields belonging to a later phase (risk score, AI
  diagnosis) stay `null` rather than being populated with plausible-looking
  placeholder values.

---

## Next steps

The build is sequenced in phases in [`docs/PRD.md` §16](docs/PRD.md). The
sequence is deliberate: database and payment simulation first, then the risk
engine, then the AI agent, then recovery actions, then the dashboard, then
polish — each phase producing something that actually works rather than a
placeholder screen.
