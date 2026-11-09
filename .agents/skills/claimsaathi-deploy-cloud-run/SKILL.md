---
name: claimsaathi-deploy-cloud-run
description: Deploy or redeploy ClaimSaathi to Google Cloud Run with Firestore and a Gemini API key in Secret Manager, and verify the deployment. Use when asked to deploy, ship, release or check the hosted demo.
---

# Deploy ClaimSaathi to Cloud Run

First deploy (creates Artifact Registry, Firestore, secret, service account):
```bash
export PROJECT_ID=<project> REGION=asia-south1 GEMINI_API_KEY=<AI Studio key>
./deploy/setup.sh
```

Redeploy after code changes (runs the unit tests in Cloud Build first):
```bash
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=$REGION
```

Verify:
```bash
URL=$(gcloud run services describe claimsaathi --region=$REGION --format='value(status.url)')
curl -s $URL/api/health          # {"status":"ok","google_ai":true}
curl -s $URL/api/config          # shows configured model IDs, never the key
```

Change a model without rebuilding:
```bash
gcloud run services update claimsaathi --region=$REGION --update-env-vars=GEMINI_MODEL=<id>
```

Rules: never put the API key in `--set-env-vars`, a file in the repo, or a chat
message — it lives only in Secret Manager. Keep `--session-affinity` and the
3600 s timeout so Gemini Live voice calls are not cut off.
