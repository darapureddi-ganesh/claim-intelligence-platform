---
name: claimsaathi-audit-review
description: Check that a ClaimSaathi claim decision is IRDAI-audit-defensible - justified by traced policy clauses, PII-redacted, and with any Gemini-written letter citation-verified. Use when asked to audit, review, or explain a claim decision.
---

# Audit a claim decision

Run the checker (needs only Python 3 and network access to the service):
```bash
python .agents/skills/claimsaathi-audit-review/scripts/audit_check.py <claim_id> \
  --url "$CLAIMSAATHI_URL"
```
It exits non-zero and lists failures when any invariant is broken:

| Invariant | Why it matters |
|---|---|
| Decision has a `policylens_justification_id` that resolves | No unjustified decision may exist |
| Justification has ≥1 traced clause, unless status is `UNCLEAR` | Every reason points at policy text |
| Audit trail has SCORED → ROUTING_DETERMINED → POLICYLENS_QUERIED → DECISION_PERSISTED in order | Reproducible sequence |
| Stored narrative has no raw Aadhaar / PAN / phone | DPDP Act data minimisation |
| Every `verdict_*` letter cites only traced clauses | The LLM did not invent a reason |

When explaining a decision to a person, quote the traced clause text; do not
re-derive coverage yourself.
