# Building ClaimSaathi in Google AI Studio

AI Studio's **Build** mode turns a chat prompt into a working web app that calls Gemini, and it can deploy that app to Cloud Run. It writes a browser app (React + TypeScript). It does not run this repo's Python backend, so the rule engine is rebuilt in TypeScript inside the app.

## What to upload

| File | Why |
|---|---|
| `data/sample_policy.txt` | The policy wording the rule engine and letters cite. If the chat won't take a `.txt`, paste its contents instead. |
| 1–2 photos of a damaged car (your own or royalty-free) | To test photo reading and Nano Banana annotation. |
| Optional: `prompts/fnol_intake.md`, `prompts/verdict_letter.md` | Tested system instructions; Build mode can reuse them word for word. |

Don't upload real claimant documents, Aadhaar, PAN or bank details.

## Step 1: paste this as the first message in Build mode

```
Build a web app called "ClaimSaathi": an insurance claims desk for Indian insurers.
Core principle: Gemini READS and EXPLAINS, but never DECIDES. Coverage and routing
are decided by deterministic TypeScript rules over the policy clauses.

I've attached sample_policy.txt (policy HC-STD-2024). Embed it in the app and split it
into clauses by their numbers (1.1, 2.1, 3.1 ...). Classify each clause as coverage,
exclusion, condition or endorsement, and tag it (health, motor, property,
pre-existing, waiting-period, alcohol, high-value).

Tabs:

1. "File a claim"
   - Textarea that accepts any Indian language, plus image/PDF/audio upload and a
     voice-note recorder.
   - Send everything to gemini-3.8-flash with a JSON responseSchema returning:
     policy_id, insured_name, claim_type (motor|health|property|life|marine|other),
     amount_claimed_inr, incident_date, reported_date, policy_start_date,
     detected_language, narrative_original, narrative_english,
     pre_existing_condition {value, evidence}, alcohol_or_drugs_involved {value, evidence},
     damaged_parts, consistency_flags [{flag, severity low|medium|high, evidence}],
     missing_information.
   - The model must only extract facts and must never decide coverage. A fact counts
     only if its evidence quote is non-empty.
   - Show the extracted facts, the English translation and the flags.
   - If policy_id or amount is missing, show what's missing and do not file.

2. Deterministic decision (plain TypeScript, no LLM):
   - Risk score from amount, days between incident and report, and weekend incident.
   - Queue: any HIGH flag -> "investigation"; amount >= 500000 -> "senior adjuster";
     low risk with no medium flag -> "fast-track"; otherwise "standard".
   - Coverage status: EXCLUDED if an evidenced fact matches an exclusion clause
     (pre-existing -> 3.1; alcohol -> 8.1; incident within 30 days of
     policy_start_date -> 3.5, computed from the dates). CONDITIONAL if routed to
     investigation. COVERED if a coverage clause matches the claim type. Otherwise UNCLEAR.
   - Record the exact clause numbers and text used ("traced clauses").
   - Before saving, redact Aadhaar (12 digits), PAN (ABCDE1234F), phone numbers and
     emails with regex, then ask gemma-4-26b-a4b-it to replace person names and street
     addresses with [NAME]/[ADDRESS]. Reject the Gemma output if any regex placeholder
     disappears.
   - Keep an audit trail: FNOL_RECEIVED, PII_REDACTED, SCORED, ROUTED, JUSTIFIED,
     each with a timestamp.

3. "Claims desk"
   - Table of claims (saved in localStorage); click one to see scores, queue,
     coverage status, traced clause text and the audit trail.
   - "Write letter" button with a language picker (English, Hindi, Telugu, Tamil,
     Kannada, Malayalam, Marathi, Bengali, Gujarati). gemini-3.8-flash returns JSON
     {decision_stated, cited_clause_refs, letter_markdown}.
   - Validate it: decision_stated must equal the coverage status, and every cited
     clause must be in the traced clauses. If validation fails, show a fixed English
     template letter instead, with a badge saying which one was used.
   - Letters end with the grievance route: the insurer's Grievance Redressal Officer,
     then IRDAI Bima Bharosa or the Insurance Ombudsman. They never promise payment.

4. "Damage photo"
   - Send an uploaded photo to gemini-nano-banana-2.1 asking for an annotated COPY
     with red outlines and labels on damaged parts, without altering anything else.
   - Show the original and the copy side by side, labelled "AI-annotated copy, not
     evidence".

Design: clean, light/dark mode, works on a phone, Google-style blue accent.
```

## Step 2: follow-up messages, one at a time

Check each step works before sending the next one.

**Voice agent (Gemini Live)**
```
Add a "Call Saathi" tab using the Gemini Live API with model gemini-3.8-live and
audio in/out. Saathi is a calm claims intake agent. It replies in the caller's language,
collects policy number, name, claim type, date, place, what happened and the amount,
reads the details back and asks for confirmation, then calls a function submit_fnol
with those fields. submit_fnol runs the same deterministic decision and saves the
claim. Saathi then reads out the first 8 characters of the claim ID and the queue.
It never promises approval and never asks for Aadhaar, PAN or bank details. Show a
live transcript.
```

**Load other policies**
```
Add a "Policies" tab where I can upload a policy PDF. gemini-3.8-flash extracts clauses
as JSON {clause_ref, node_type, verbatim_text, tags}. Accept a clause only if
verbatim_text appears exactly in a transcription of the PDF (ignore whitespace and
case); list rejected clauses separately. Claims can then pick which policy to use.
```

**Demo polish**
```
Add three sample buttons on "File a claim": a Hindi motor accident, a Telugu
hospitalisation, and an English health claim that mentions diabetes since 2020.
Add a pipeline strip: Gemini reads -> Gemma redacts -> rules decide -> Gemini explains.
```

## Step 3: test before you deploy

- Hindi sample → Hindi detected, English translation shown, claim filed.
- English diabetes sample → status EXCLUDED, clause 3.1 traced.
- Edit a letter's JSON in the code view to cite clause 9.9 → the template fallback
  should appear. This proves the validator works.

## Step 4: deploy

Use the **Deploy** option in Build mode to publish to Cloud Run on your Google Cloud
project. Before it goes public, make sure the API key isn't shipped to the browser: use
the deployment's built-in key proxy, or move the calls behind a server.

## Testing the prompts on their own

In AI Studio's normal chat playground, paste a file from `prompts/` into **System
instructions**, turn on **Structured output** with the matching schema
(`src/gemini/schemas.py`), and try real-looking inputs. When a prompt works better,
copy it back into `prompts/`. The Python app picks up the change with no code changes.
