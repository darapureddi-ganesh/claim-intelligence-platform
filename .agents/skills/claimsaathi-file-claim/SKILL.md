---
name: claimsaathi-file-claim
description: File an insurance claim (FNOL) into ClaimSaathi from text, photos, PDFs or voice notes in any Indian language, and report the routing decision and policy clauses. Use when asked to submit, register, test or bulk-load claims.
---

# File a claim in ClaimSaathi

Base URL: `$CLAIMSAATHI_URL` (default `http://localhost:8080`).

## Unstructured / multimodal (Gemini reads it)
```bash
curl -s -X POST "$CLAIMSAATHI_URL/api/intake" \
  -F 'text=मेरी कार का कल हैदराबाद में एक्सीडेंट हुआ। पॉलिसी HC-STD-2024, नाम रवि कुमार, अनुमान ₹85,000' \
  -F 'files=@/path/to/damage.jpg' -F 'files=@/path/to/estimate.pdf'
```
- `submitted: false` means Gemini could not find a policy number or amount; show
  the `missing` list to the user instead of guessing values.
- To preview the extraction without filing, call `/api/intake/extract` with the same form.

## Structured JSON
```bash
curl -s -X POST "$CLAIMSAATHI_URL/api/claims" -H 'Content-Type: application/json' -d '{
  "policy_id":"HC-STD-2024","insured_name":"Priya Sharma","claim_type":"health",
  "amount_claimed":250000,"incident_date":"2026-11-01","reported_date":"2026-11-03",
  "narrative":"Emergency appendectomy at Apollo Chennai"}'
```

## Reporting back
Always report: claim id, `routing_decision.assigned_queue`, `justification.confidence`
and the `clause_ref` of each `justification.traced_clauses` entry. Never describe the
coverage status as an approval or rejection — it is a triage outcome for an adjuster.

## Rules
- Do not invent policy numbers, amounts or dates for real claimants.
- Do not paste Aadhaar, PAN or bank numbers into prompts; the service redacts them,
  but they should not be sent at all unless the user supplied them.
