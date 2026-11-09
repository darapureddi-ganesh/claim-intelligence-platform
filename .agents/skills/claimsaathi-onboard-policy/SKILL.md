---
name: claimsaathi-onboard-policy
description: Load a new insurer's policy wording (text or scanned PDF) into the ClaimSaathi PolicyLens knowledge graph with Gemini, then check the verbatim-grounding report. Use when onboarding an insurer, product or endorsement.
---

# Onboard a policy wording

1. Pick a stable `policy_id` (the insurer's product code, e.g. `MOTOR-PKG-2026`).
2. Load it:
   ```bash
   # PDF or scan — Gemini transcribes, then extracts clauses
   curl -s -X POST "$CLAIMSAATHI_URL/api/policies/upload" \
     -F policy_id=MOTOR-PKG-2026 -F 'policy_name=Private Car Package' -F file=@wording.pdf
   # Plain text
   curl -s -X POST "$CLAIMSAATHI_URL/api/policies" -H 'Content-Type: application/json' \
     -d '{"policy_id":"MOTOR-PKG-2026","policy_name":"Private Car Package","wording_text":"...","extractor":"gemini"}'
   ```
3. Read `rejected_clauses`. Each one is a clause Gemini paraphrased instead of copying
   verbatim, so it was kept out of the graph. If an important exclusion was rejected,
   re-run with `"extractor":"rules"` or fix the source text — never hand-edit clause text.
4. Verify coverage: `GET /api/policies/MOTOR-PKG-2026/clauses` and confirm every
   exclusion in the wording appears with `node_type: "exclusion"`.
5. Smoke test with one claim per claim type using the `claimsaathi-file-claim` skill.

A `409`/`422` "already loaded" means the ID is taken; choose a new version suffix.
