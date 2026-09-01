# RevenueRecover AI

An AI revenue recovery agent that detects revenue at risk, diagnoses the cause,
selects a recovery intervention, executes a bounded recovery workflow, and
measures the money actually recovered.

```
DETECT → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER
```

Built for the **AI Revenue Recovery** hackathon track.

> **Status: pre-implementation.** This repository currently holds the product
> requirements and the environment prerequisites. See [`docs/PRD.md`](docs/PRD.md)
> for the full specification, architecture, build phases, and acceptance
> criteria.

---

## Repository contents

| Path | Purpose |
|---|---|
| `docs/PRD.md` | The living product requirements document — source of truth |
| `.env.example` | Environment variable template |
| `docker-compose.yml` | PostgreSQL 16 for local development |
| `backend/requirements.txt` | Pinned Python dependencies |
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

### 4. Frontend environment

Not yet scaffolded — see Phase 7 in the PRD.

---

## Next steps

The build is sequenced in phases in [`docs/PRD.md` §16](docs/PRD.md). The
sequence is deliberate: database and payment simulation first, then the risk
engine, then the AI agent, then recovery actions, then the dashboard, then
polish — each phase producing something that actually works rather than a
placeholder screen.
