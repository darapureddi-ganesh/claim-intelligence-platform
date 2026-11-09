# ClaimSaathi: Google Buildathon submission

**Track:** Build with Google AI, deploy on Google Cloud
**One-liner:** A multilingual, multimodal claims desk for Indian insurers. Gemini reads, a zero-LLM policy graph decides, and Gemini explains with every sentence traced to a policy clause.

---

## 1. Problem

- India's general and health insurers handle millions of claims every year, and mid-market insurers, MGAs and TPAs still triage much of that work by hand.
- First notice of loss arrives as a Hindi WhatsApp message, a Telugu phone call, a blurry photo of a bumper, or a scanned discharge summary. English-only OCR and form-based portals fail exactly the customers who most need help.
- An LLM can't simply be handed the decision. IRDAI expects every claim decision to be explainable, and repudiations must cite the policy terms. A model that "usually" gets the reason right is not auditable.
- Under the DPDP Act, 2023, raw Aadhaar numbers, phone numbers and names shouldn't leak into logs and analytics.

## 2. Solution

ClaimSaathi splits the work so that each part is done by the right tool:

| Step | Who does it | Why |
|---|---|---|
| Understand the claimant (voice, text, photos, PDFs; English + 12 Indian languages) | **Gemini / Gemini Live** | Multimodal + multilingual is what LLMs are good at |
| Strip personal data before storage | **Gemma** (self-hostable) + regex | Open weights → can run inside the insurer's VPC |
| Score and route | Pilot ML models + deterministic rules | Tunable per insurer, explainable |
| Decide coverage and justify | **PolicyLens graph — zero LLM** | Every reason is a node that holds verbatim policy text |
| Explain to the policyholder in their language | **Gemini**, then a citation validator | Fluent letters that can't change the decision or invent clauses |
| Help adjusters triage photos | **Nano Banana** annotated copies | Original preserved; SHA-256 in the audit log |

## 3. Google AI and Google Cloud usage

| Required element | Used | How |
|---|---|---|
| Gemini | ✅ | FNOL extraction with `response_schema`, policy clause extraction + PDF transcription, multilingual verdict letters |
| Gemini Live | ✅ | "Saathi" phone agent over a Cloud Run WebSocket bridge, with `check_policy` and `submit_fnol` function calling |
| Nano Banana | ✅ | Damage-photo annotation for adjusters |
| Gemma | ✅ | PII redaction; Gemini API by default, `GEMMA_ENDPOINT` for self-hosted |
| Gemini Omni / Lyria | — | Deliberately not used: generated video or music doesn't fit a regulated claims workflow, and generated "reconstructions" of an incident would be a fabricated-evidence risk |
| Google AI Studio | ✅ | API key; system prompts in `prompts/*.md` are kept AI Studio-ready |
| Google Antigravity | ✅ | Workspace Agent Skills in `.agents/skills/` |
| Google Agent Skills | ✅ | 4 skills: file a claim, onboard a policy, audit a decision (with a checker script), deploy to Cloud Run |
| Google Cloud | ✅ | Cloud Run (`asia-south1`), Firestore, Secret Manager, Artifact Registry, Cloud Build (tests gate the deploy) |

## 4. Demo script (3 minutes)

1. **Voice (45 s).** Open *Call Saathi*. Speak in Hindi: *"मेरी कार का कल एक्सीडेंट हुआ…"*. Saathi asks for the policy number, reads it back, confirms, files the claim, and reads out the claim number and next step. The claim card appears on screen.
2. **Documents (45 s).** On *File a claim*, attach a photo of a damaged car and a repair estimate, and type two lines in Telugu. *Read and file claim*: Gemini returns the English translation, the documents it read, and an evidence flag (e.g. "estimate dated before the accident"). The claim is escalated to investigation by a **rule**, not by the model.
3. **Explainability (45 s).** In the *Claims desk*, open the claim: severity, complexity and fraud scores; the **exact policy clauses** behind the decision; and the full audit trail including `PII_REDACTED`. Click *Write letter* in Tamil. The badge reads "Gemini · citations verified".
4. **Guardrail (30 s).** On *Policies*, upload a policy PDF. Gemini extracts clauses, and the response lists any clause it **rejected because it wasn't verbatim**. Every graph node is real policy text.
5. **Close (15 s).** It runs on Cloud Run in Mumbai, it's one command to deploy, and every decision is defensible to IRDAI.

## 5. What's technically interesting

- **Verbatim grounding for knowledge-graph construction.** LLM extraction, but nothing enters the graph unless it is a substring of the source document (whitespace- and case-normalised).
- **Validator-gated generation.** The letter model gets the decision as a fixed input and must echo it. Any citation outside the traced set, including one found only in the prose, sends it to a deterministic fallback. Tested in `tests/gemini/test_verdict.py`.
- **LLM facts are evidence, not verdicts.** Exclusion-relevant facts are only used with a supporting quote; the waiting period is computed from dates by code.
- **Server-side Live bridge.** No API key in the browser; tool calls run the same audited pipeline as every other channel.
- **Offline test suite.** 81 tests, with Gemini swapped for a fake client, run in Cloud Build before every deploy.

## 6. Impact

- **Inclusion:** claimants file in their own language, by voice, without forms.
- **Speed:** clean low-risk claims can be fast-tracked minutes after the first call. Inconsistent ones reach investigators with the evidence already quoted.
- **Compliance:** every decision maps to clause text, every letter is citation-checked, and PII is minimised by default.

## 7. Roadmap

Train the scoring models on real claims data; scope PolicyLens matching to the claim's own policy; add a Neo4j graph store; add WhatsApp intake; host Gemma on Cloud Run GPU inside the insurer's VPC; add an IRDAI-format repudiation pack generator.
