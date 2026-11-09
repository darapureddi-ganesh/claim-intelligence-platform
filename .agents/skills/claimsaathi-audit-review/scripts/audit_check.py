"""Verify the audit invariants of one ClaimSaathi claim. Exit 1 on any failure."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

PII = {
    "aadhaar": re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "phone": re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
}
ORDER = ["SCORED", "ROUTING_DETERMINED", "POLICYLENS_QUERIED", "DECISION_PERSISTED"]


def canon(ref: str) -> str:
    return re.sub(r"(?i)^(section|clause|article|part)\s+", "", ref.strip()).rstrip(".")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("claim_id")
    ap.add_argument("--url", default="http://localhost:8080")
    a = ap.parse_args()
    with urllib.request.urlopen(f"{a.url.rstrip('/')}/api/claims/{a.claim_id}") as r:
        d = json.load(r)

    failures: list[str] = []
    rd, j = d.get("routing_decision"), d.get("justification")
    if not rd:
        failures.append("no routing decision")
    elif not j or j.get("query_id") != rd.get("policylens_justification_id"):
        failures.append("justification id missing or does not resolve")
    if j and j["confidence"] != "UNCLEAR" and not j["traced_clauses"]:
        failures.append("decision not traced to any clause")

    actions = [e["action"] for e in d.get("audit_trail", [])]
    idx = [actions.index(x) if x in actions else -1 for x in ORDER]
    if -1 in idx or idx != sorted(idx):
        failures.append(f"audit sequence broken: {actions}")

    text = d["claim"].get("raw_fnol_text", "") + " " + str(
        d["claim"].get("metadata", {}).get("narrative_original", ""))
    for name, pat in PII.items():
        if pat.search(text):
            failures.append(f"unredacted {name} in stored narrative")

    traced = {canon(c["clause_ref"]) for c in (j or {}).get("traced_clauses", [])}
    for key, letter in d.get("extras", {}).items():
        if key.startswith("verdict_"):
            stray = {canon(r) for r in letter.get("cited_clause_refs", [])} - traced
            if stray:
                failures.append(f"{key} cites untraced clauses {sorted(stray)}")

    print(json.dumps({"claim_id": a.claim_id, "ok": not failures, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
