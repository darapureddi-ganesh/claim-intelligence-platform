# ClaimSaathi: claims intelligence on Google AI

**File an insurance claim in any Indian language, by voice, photo or document, and get a decision every auditor can trace back to the policy wording.**

ClaimSaathi is the Google AI edition of the Claims Intelligence Platform (ClaimIQ + PolicyLens + VerdictLens). It is built with **Gemini, Gemini Live, Nano Banana and Gemma**, prototyped in **Google AI Studio**, developed with **Google Antigravity** and **Agent Skills**, and deployed on **Google Cloud Run** with Firestore and Secret Manager.

> Built for the Google Buildathon. Submission write-up: [BUILDATHON.md](BUILDATHON.md). Original Phase 1 docs: [docs/PHASE1.md](docs/PHASE1.md).

---

## The idea in one line

> **Gemini reads. A rule graph decides. Gemini explains, and a validator checks every sentence.**

Indian mid-market insurers can't put an LLM in charge of claim decisions: IRDAI expects every decision to be explainable and auditable. But most of their claims work is reading: Hindi WhatsApp messages, Telugu voice notes, photos of a dented car, scanned hospital bills. ClaimSaathi uses Google AI where it is strongest (multilingual, multimodal understanding and language generation) and keeps the decision itself deterministic and clause-traced.

```
 Claimant (voice · text · photos · PDFs · any language)
        │
        ▼
 ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐
 │ Gemini Live  │  │ Gemini       │  │ Gemma (open weights)         │
 │ voice agent  │  │ multimodal   │─▶│ PII redaction: names,        │
 │ "Saathi"     │─▶│ FNOL reader  │  │ addresses (+ regex for       │
 └──────────────┘  │ facts +      │  │ Aadhaar/PAN/phone)           │
                   │ evidence     │  └──────────────┬───────────────┘
                   └──────────────┘                 ▼
                                   ┌──────────────────────────────────┐
                                   │ ClaimIQ: ML scoring + rule-based │
                                   │ routing (+ deterministic         │
                                   │ escalation on evidence flags)    │
                                   └──────────────┬───────────────────┘
                                                  ▼
 Policy PDF ──▶ Gemini clause extractor ──▶ ┌──────────────────────────┐
               (verbatim-grounding check)   │ PolicyLens knowledge     │
                                            │ graph — ZERO LLM         │
                                            │ every reason = a clause  │
                                            └──────────────┬───────────┘
                                                           ▼
                        ┌───────────────────────────────────────────────┐
                        │ VerdictLens: Gemini writes the letter in the  │
                        │ claimant's language → validator rejects any   │
                        │ draft that changes the decision or cites an   │
                        │ untraced clause → deterministic fallback      │
                        └───────────────────────────────────────────────┘
 Adjuster view: Nano Banana annotated damage photos (original hash preserved)
```

## Where each Google technology is used

| Google technology | What it does in ClaimSaathi | Code |
|---|---|---|
| **Gemini** (`gemini-3.8-flash`) | Reads claim text, photos, PDFs and voice notes in English and 12 Indian languages, returning structured facts with verbatim evidence and consistency flags | `src/gemini/intake.py` |
| **Gemini** | Turns policy wordings (incl. scanned PDFs) into graph clauses; any clause that isn't a verbatim copy of the source is rejected | `src/gemini/policy_extractor.py` |
| **Gemini** | Writes the claim-status letter in the claimant's language, checked by a citation validator | `src/gemini/verdict.py` |
| **Gemini Live** (`gemini-3.8-live`) | Real-time voice claim intake: asks questions, reads details back, calls `submit_fnol`, reads out the claim number | `src/gemini/live.py` |
| **Nano Banana** (`gemini-nano-banana-2.1`) | Annotated copy of damage photos for adjusters; the original's SHA-256 is kept as evidence | `src/gemini/vision.py` |
| **Gemma** (`gemma-4-26b-a4b-it`) | Redacts names and addresses before anything is stored or logged; can be self-hosted in the insurer's VPC (DPDP Act) | `src/gemini/pii.py` |
| **Google AI Studio** | API key, plus every system prompt lives in `prompts/*.md` so it can be pasted into AI Studio, tuned, and copied back | `prompts/` |
| **Google Antigravity + Agent Skills** | `.agents/skills/` teaches Antigravity agents to file claims, onboard policies, audit decisions and deploy | `.agents/skills/` |
| **Google Cloud** | Cloud Run (app + WebSocket voice), Firestore, Secret Manager, Artifact Registry, Cloud Build CI/CD, `asia-south1` (Mumbai) | `Dockerfile`, `cloudbuild.yaml`, `deploy/` |

All model IDs are environment variables. Run `make models` to list what your key can call and swap in newer ones without code changes.

## Quick start (local)

```bash
pip install -r requirements.txt pytest pytest-asyncio
python -m spacy download en_core_web_sm      # optional; a blank model is used otherwise
cp .env.example .env                         # add GEMINI_API_KEY from https://aistudio.google.com/apikey
make run                                     # http://localhost:8080
```

With no key, the app still runs in **rules-only mode**: structured claims, routing, PolicyLens justifications and template letters all work. The Gemini features return a clear 503.

```bash
pytest -q          # 81 tests; Gemini is replaced by a fake client, no network needed
```

## Deploy to Google Cloud

```bash
export PROJECT_ID=<your-project> REGION=asia-south1 GEMINI_API_KEY=<AI Studio key>
make deploy        # enables APIs, creates Firestore, Artifact Registry, secret, SA; Cloud Build → Cloud Run
```

Redeploy after changes with `make redeploy`. Cloud Build runs the test suite before building. To switch to Vertex AI (service-account auth, no key), see `deploy/use-vertex.sh`.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/intake` | multipart `text` + `files[]` → Gemini reads → Gemma redacts → score → route → justify |
| `POST` | `/api/intake/extract` | Same reading step without filing (preview) |
| `POST` | `/api/claims` | Structured JSON claim (no AI needed) |
| `GET`  | `/api/claims`, `/api/claims/{id}` | List / detail with decision, justification, audit trail |
| `POST` | `/api/claims/{id}/verdict?language=te` | Gemini letter in the claimant's language, citation-validated |
| `POST` | `/api/vision/annotate` | Nano Banana annotated damage photo |
| `POST` | `/api/policies`, `/api/policies/upload` | Load a policy wording (text or PDF) into the graph |
| `GET`  | `/api/policies/{id}/clauses` | Inspect graph clauses |
| `WS`   | `/api/live/fnol` | Gemini Live voice intake (PCM16 16 kHz in, 24 kHz out) |
| `GET`  | `/api/config` | Configured models and backend (never the key) |

Interactive docs: `/docs`.

## Guardrails that make it auditable

1. **No justification, no decision.** The original `TriageService` invariant is unchanged: a routing decision is never persisted without a PolicyLens justification ID.
2. **The LLM never routes.** Gemini's consistency flags only feed a *deterministic* rule: a high-severity flag sends the claim to investigation, and a medium flag blocks fast-track.
3. **Facts need evidence.** Exclusion-relevant facts (pre-existing disease, alcohol) are only used when Gemini quotes the supporting text. The waiting period is computed by code from dates, never asked of the model.
4. **Graph clauses are verbatim.** Gemini-extracted clauses that aren't exact substrings of the source wording are rejected and reported.
5. **Letters can't drift.** A Gemini letter that states a different status, or cites any clause the graph didn't trace, is discarded for a deterministic template.
6. **PII never lands in storage.** Regex catches Aadhaar/PAN/phone/email/IFSC; Gemma adds names/addresses; a Gemma output that would un-redact anything is rejected.
7. **Evidence is never altered.** Nano Banana only produces a separate, labelled copy; the original photo's SHA-256 goes to the audit log.

## Project layout (new in this edition)

```
src/gemini/          Google AI adapters (config, client, intake, pii, policy_extractor, verdict, vision, live)
src/platform/        Cloud Run app: FastAPI (app.py), orchestration (service.py), Firestore/in-memory store
web/index.html       Claimant + adjuster UI (multimodal filing, voice call, claims desk, policies)
prompts/             System prompts, AI Studio–ready
.agents/skills/      Agent Skills for Google Antigravity
deploy/              setup.sh (one-shot GCP setup + deploy), use-vertex.sh
cloudbuild.yaml      Test → build → push → deploy
tests/gemini/        Offline tests with a fake Gemini client
```

The original Phase 1 services (`src/claimiq`, `src/policylens`, `src/verdictlens`, Postgres/Redis via `docker-compose`, `Dockerfile.dev`) are unchanged and still run as before (`make dev`).

## Known limitations

- Scoring models are still the pilot's synthetic-data models; they need training on real claims data.
- In rules-only mode the keyword extractor groups clauses by section ("Block 3"), so justifications are coarse. The Gemini extractor produces clause-level nodes ("3.1").
- The PolicyLens reasoning engine matches clauses by tag across all loaded policies, not only the claim's policy (inherited from Phase 1).
- Gemini Live model IDs differ between the Gemini API and Vertex AI; set `GEMINI_LIVE_MODEL` to match your backend.
