# Claims Intelligence Platform

India-native claims decisioning infrastructure for mid-market insurers, MGAs, and TPAs.

Three components — **ClaimIQ**, **PolicyLens**, and **VerdictLens** — that share one data and reasoning core, deployed as a single integrated stack.

---

## Why this exists

Mid-market Indian insurers are locked out of enterprise suites (Guidewire, Duck Creek) on cost/timeline, and underserved by global point solutions (CLARA Analytics, Sprout.ai) that aren't built for Indian data, language, or IRDAI compliance.

The platform's three defensible advantages:

| Advantage | What it means |
|---|---|
| **Segment gap** | No India-native player serving the mid-market at this price point |
| **Bundling gap** | Nobody combines triage + zero-LLM explainability + denial documentation as one product |
| **Compliance-by-architecture** | The zero-LLM graph is a structural answer to IRDAI auditability — not a marketing claim layered on top of an LLM |

---

## Components

```
FNOL Intake
     │
     ▼
┌──────────────────────┐
│       ClaimIQ        │  Phase 1  ← you are here
│  Triage & Routing    │
│  FastAPI + XGBoost   │
│  + PostgreSQL        │
└──────────┬───────────┘
           │ every decision triggers a justification request
           ▼
┌──────────────────────┐
│      PolicyLens      │  Phase 1  ← you are here
│  Rule-based Policy   │
│  Knowledge Graph     │
│  spaCy + NetworkX    │
│  (zero-LLM)          │
└──────────┬───────────┘
           │ same graph, reused
           ▼
┌──────────────────────┐
│     VerdictLens      │  Phase 2  (stub — not yet built)
│  Denial Explanation  │
│  & Compliance Docs   │
└──────────────────────┘
```

### ClaimIQ
Handles FNOL intake, ML-based scoring, and intelligent queue routing.

- **Intake**: accepts structured JSON or plain-text FNOL submissions; OCR stub for Phase 1d multilingual expansion
- **Scoring**: three independent models (severity, complexity, fraud propensity) via scikit-learn/GradientBoosting; XGBoost-ready
- **Routing**: deterministic threshold-based assignment to four queues — `standard`, `senior-adjuster`, `fraud-investigation`, `fast-track`
- **Reserve suggestion**: calculated as a risk-tier multiplier on the claimed amount
- **Queue**: Redis + RQ for async processing during surge events (catastrophe claims spikes)

### PolicyLens
The shared reasoning layer — not a bolt-on, not a chatbot. Both ClaimIQ and VerdictLens query it.

- **NLP extraction**: spaCy pipeline splits policy wording into clause blocks, classifies each as coverage / exclusion / condition / endorsement, infers tags (claim type, pre-existing, waiting-period, high-value)
- **Knowledge graph**: NetworkX DiGraph for the pilot; Neo4j adapter interface stubbed for production migration
- **Reasoning engine**: pure rule-based graph traversal — **zero LLM**. Every justification traces back to a specific policy clause node. IRDAI-audit-defensible by construction.

### VerdictLens (Phase 2)
Reuses the PolicyLens graph to generate claims-denial explanation documents and IRDAI-compliant compliance documentation. Phase 2 build adds a document-formatting layer only — the reasoning infrastructure is already in place from Phase 1.

---

## Architecture

**Hexagonal (Ports and Adapters)**. The core domain has zero dependency on any specific insurer's systems. New customer onboarding = write a new adapter, not modify the core.

```
┌─────────────────────────────────────────┐
│              Core Domain                │
│  (triage rules, scoring interfaces,     │
│   graph reasoning interfaces)           │
└──────────┬──────────────────┬───────────┘
           │ Port             │ Port
  ┌────────▼──────┐   ┌───────▼────────┐
  │  Adapter:     │   │  Adapter:      │
  │  Insurer A    │   │  Insurer B     │
  │  policy admin │   │  legacy CSV    │
  └───────────────┘   └────────────────┘
```

**Non-negotiable invariant**: every routing decision must carry a PolicyLens justification ID before it is persisted to the database. If PolicyLens is unavailable, the `TriageService` raises `JustificationRequiredError` and the decision is not saved.

---

## Project Layout

```
claim-intelligence-platform/
├── src/
│   ├── core/                      # Hexagonal center — zero framework dependencies
│   │   ├── domain/
│   │   │   ├── models.py          # Claim, RoutingDecision, AuditEntry (pure dataclasses)
│   │   │   └── ports.py           # IScoringEngine, IRoutingEngine, IPolicyLensPort, IDocumentParser
│   │   └── audit.py               # AuditService
│   │
│   ├── claimiq/                   # Phase 1a — FNOL intake, scoring, routing
│   │   ├── api/routes/
│   │   │   └── claims.py          # POST /claims, GET /claims/{id}
│   │   ├── scoring/
│   │   │   ├── engine.py          # XGBoostScoringEngine
│   │   │   └── features.py        # Feature extraction from claim fields
│   │   ├── routing/
│   │   │   └── engine.py          # RuleBasedRoutingEngine
│   │   ├── intake/
│   │   │   ├── parser.py          # EnglishTextFNOLParser (OCR stubbed)
│   │   │   └── normalizer.py      # Amount/date/claim-type normalisation
│   │   ├── adapters/
│   │   │   ├── base.py            # AbstractInsuranceAdapter
│   │   │   ├── generic_csv.py     # GenericCSVAdapter (legacy exports)
│   │   │   └── policylens_http.py # PolicyLensHTTPAdapter (Phase 1c wiring)
│   │   ├── services/
│   │   │   └── triage.py          # TriageService — orchestrates the full pipeline
│   │   ├── db/
│   │   │   ├── models.py          # SQLAlchemy ORM models
│   │   │   ├── repository.py      # ClaimRepository, RoutingDecisionRepository, AuditLogRepository
│   │   │   └── session.py         # Async SQLAlchemy session factory
│   │   └── worker/
│   │       └── tasks.py           # RQ task: process_fnol_async
│   │
│   ├── policylens/                # Phase 1b — policy knowledge graph + reasoning
│   │   ├── api/routes/
│   │   │   ├── policies.py        # POST /policies, GET /policies/{id}
│   │   │   └── query.py           # POST /query
│   │   ├── graph/
│   │   │   ├── models.py          # PolicyNode, PolicyEdge, NodeType, EdgeRelation
│   │   │   ├── store.py           # NetworkXGraphStore (IGraphStore)
│   │   │   └── neo4j_adapter.py   # Neo4jGraphStore stub (migration path)
│   │   ├── nlp/
│   │   │   └── extractor.py       # PolicyClauseExtractor (spaCy)
│   │   ├── loaders/
│   │   │   └── policy_loader.py   # PolicyLoader: text → graph
│   │   └── reasoning/
│   │       └── engine.py          # RuleBasedReasoningEngine (zero LLM)
│   │
│   └── verdictlens/               # Phase 2 stub
│       └── api/routes/
│           └── denials.py         # POST /denials/{claim_id}/explain → 501
│
├── migrations/
│   └── versions/
│       └── 001_initial_schema.py  # claims, routing_decisions, audit_log, adjusters, queues
│
├── tests/
│   ├── unit/
│   │   ├── test_scoring.py
│   │   ├── test_routing.py
│   │   ├── test_graph.py
│   │   └── test_reasoning.py
│   ├── integration/
│   │   ├── test_policylens_api.py
│   │   └── test_triage_flow.py    # End-to-end: FNOL → decision with justification
│   └── fixtures/
│       ├── sample_claims.json     # 5 test FNOLs (motor, health, property)
│       └── sample_policy.txt      # IRDAI-style policy wording (English)
│
├── scripts/
│   ├── seed_adjusters.py          # Populate queues + adjusters table
│   └── seed_policy_graph.py       # Load sample policy into PolicyLens
│
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Docker and Docker Compose

### 1. Clone and install

```bash
git clone <repo>
cd claim-intelligence-platform
pip install -e ".[dev]"
```

### 2. Start infrastructure

```bash
docker-compose up -d postgres redis
```

### 3. Run database migrations

```bash
alembic upgrade head
```

Or with the Makefile shortcut:

```bash
make migrate
```

### 4. Seed reference data

```bash
python scripts/seed_adjusters.py     # Creates adjuster queues + adjusters
python scripts/seed_policy_graph.py  # Loads sample IRDAI-style policy into PolicyLens
```

### 5. Start the services

**Terminal 1 — PolicyLens** (must start first, ClaimIQ calls it):
```bash
uvicorn src.policylens.main:app --reload --port 8001
```

**Terminal 2 — ClaimIQ**:
```bash
uvicorn src.claimiq.main:app --reload --port 8000
```

**Terminal 3 — RQ Worker** (optional, for async mode):
```bash
rq worker --url redis://localhost:6379/0 fnol-intake
```

### 6. Submit a test claim

```bash
curl -X POST http://localhost:8000/claims \
  -H "Content-Type: application/json" \
  -d '{
    "policy_id": "HC-STD-2024",
    "insured_name": "Priya Sharma",
    "claim_type": "health",
    "amount_claimed": 250000,
    "incident_date": "2024-03-01",
    "reported_date": "2024-03-03",
    "narrative": "Hospitalization for surgery at Apollo Hospital, Chennai."
  }'
```

The response includes:
- `routing_decision` — queue assignment, reserve suggestion, scores
- `policylens_justification_id` — UUID of the clause-traced justification
- `audit_trail` — every step logged with timestamp and actor

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (no services required)
pytest tests/unit/ -v

# Integration tests (no DB/services required — uses in-memory repos)
pytest tests/integration/ -v
```

Current status: **40/40 passing**.

---

## API Reference

### ClaimIQ (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/claims` | Submit FNOL — scores, routes, and justifies synchronously |
| `GET` | `/claims/{id}` | Retrieve claim with routing decision and full audit trail |
| `GET` | `/health` | Health check |

**POST /claims — request body**
```json
{
  "policy_id": "HC-STD-2024",
  "insured_name": "Rajesh Kumar",
  "claim_type": "health",
  "amount_claimed": 500000,
  "incident_date": "2024-06-01",
  "reported_date": "2024-06-02",
  "narrative": "Emergency hospitalisation.",
  "language": "en",
  "metadata": {}
}
```

Supported `claim_type` values: `motor`, `health`, `property`, `life`, `marine`, `other`.

**POST /claims — response**
```json
{
  "claim": { "id": "...", "status": "ROUTED", ... },
  "routing_decision": {
    "severity_score": 0.72,
    "complexity_score": 0.61,
    "fraud_propensity_score": 0.08,
    "decision_type": "route_to_senior",
    "assigned_queue": "senior-adjuster",
    "reserve_suggestion": 550000,
    "policylens_justification_id": "..."
  },
  "audit_trail": [
    { "action": "SCORED", "actor": "claimiq.scoring", ... },
    { "action": "POLICYLENS_QUERIED", "source_clause_ref": "Section 5.1", ... },
    { "action": "DECISION_PERSISTED", ... }
  ]
}
```

### PolicyLens (port 8001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/policies` | Load a policy wording document into the graph |
| `GET` | `/policies/{id}` | Get node/edge counts for a loaded policy |
| `POST` | `/query` | Justify a routing or reserve decision |
| `GET` | `/health` | Health check |

**POST /query — request body**
```json
{
  "claim_id": "uuid",
  "claim_type": "health",
  "decision_type": "route_to_senior",
  "relevant_facts": {
    "amount_claimed": "750000",
    "pre_existing_condition": false,
    "fraud_propensity_score": 0.1
  }
}
```

**POST /query — response**
```json
{
  "query_id": "...",
  "justification_text": "Decision [Route To Senior] — claim is covered. Supporting clause(s): Section 5.1. Claimed amount: INR 750000.",
  "traced_clauses": [
    {
      "node_id": "pol:HC-STD-2024:coverage:5",
      "clause_ref": "Section 5.1",
      "text": "Claims exceeding INR 5,00,000 must be reviewed by a Senior Claims Adjuster.",
      "tags": ["coverage", "health", "high-value"]
    }
  ],
  "confidence": "COVERED",
  "timestamp": "2024-07-07T..."
}
```

Interactive API docs are available at `http://localhost:8000/docs` and `http://localhost:8001/docs`.

---

## Database Schema

```sql
claims                  — one row per FNOL submission
routing_decisions       — one row per claim; policylens_justification_id NOT NULL (DB-enforced)
audit_log               — append-only; every triage step logged with claim_id + timestamp
adjusters               — adjuster pool with skills, geography, workload
queues                  — routing target queues with skill requirements
```

The `policylens_justification_id NOT NULL` constraint is enforced at both the application layer (`TriageService`) and the database level — the architecture makes it structurally impossible to persist an unjustified decision.

---

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL URL |
| `DATABASE_SYNC_URL` | `postgresql+psycopg2://...` | Sync URL (Alembic + RQ worker) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `POLICYLENS_URL` | `http://localhost:8001` | PolicyLens service URL |
| `SECRET_KEY` | — | Change in production |
| `POLICYLENS_GRAPH_PATH` | `policylens_graph.json` | Graph persistence file path |

Routing thresholds (tunable per insurer without code changes):

| Variable | Default | Description |
|----------|---------|-------------|
| `SENIOR_ADJUSTER_THRESHOLD` | `0.65` | Overall risk score → senior queue |
| `FRAUD_UNIT_THRESHOLD` | `0.60` | Fraud propensity score → fraud queue |
| `FAST_TRACK_THRESHOLD` | `0.25` | Overall risk score → fast-track queue |

---

## Extending for a New Insurer

The hexagonal architecture means onboarding a new insurer = write one adapter, not touch the core.

1. **Create an adapter** in `src/claimiq/adapters/`:

```python
class MagmaPolicyAdminAdapter(AbstractInsuranceAdapter):
    @property
    def adapter_id(self) -> str:
        return "magma_policy_admin"

    def fetch_policy_context(self, policy_id: str) -> dict:
        # Call Magma's API / legacy DB
        ...

    def push_decision(self, claim: Claim, decision_summary: dict) -> None:
        # Write back to Magma's system
        ...
```

2. **Load their policy wording** into PolicyLens via `POST /policies`.

3. **Point the environment** at their database and PolicyLens instance.

The `TriageService`, scoring models, and reasoning engine are unchanged.

---

## Build Roadmap

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1a | ClaimIQ core (intake, scoring, routing) | ✅ Done |
| 1b | PolicyLens core graph + rule engine | ✅ Done |
| 1c | ClaimIQ ↔ PolicyLens integration | ✅ Done |
| 1d | Multilingual OCR/NLP layer (Hindi + regional) | Stubbed — `IDocumentParser` port is ready |
| 2 | VerdictLens denial explanation documents | Stub only — PolicyLens graph is already populated |

**Phase 1d** (multilingual): plug in a new `IDocumentParser` implementation with an OCR backend (e.g. Google Document AI, AWS Textract, or a self-hosted Tesseract pipeline). The rest of the pipeline is unchanged.

**Phase 2** (VerdictLens): add a document-formatting layer on top of the existing PolicyLens graph. No new reasoning infrastructure required.

---

## Key Design Decisions

**Why zero LLM in PolicyLens?**
IRDAI audit requirements demand that every claims decision be traceable to a specific policy clause. LLM outputs are non-deterministic and cannot be pinned to a source clause. Rule-based graph traversal gives a deterministic, reproducible answer for every query — the same input always produces the same output and the same clause reference.

**Why Hexagonal Architecture?**
Target customers run heterogeneous, often legacy policy admin systems. Hexagonal ensures the core triage/reasoning logic is never tangled with any specific insurer's database schema or API shape. When Insurer A's legacy system changes, only their adapter changes.

**Why NetworkX for the pilot?**
Neo4j adds operational overhead (separate service, Cypher query language, cluster management) that isn't justified until the graph needs to serve multiple tenants at scale. NetworkX runs in-process, persists to a single JSON file, and the `IGraphStore` interface means migration to Neo4j requires only swapping the implementation class — the reasoning engine is unchanged.
