#!/usr/bin/env bash
# One-time Google Cloud setup + first deploy for ClaimSaathi.
#
#   export PROJECT_ID=my-project REGION=asia-south1
#   export GEMINI_API_KEY=...   # from https://aistudio.google.com/apikey
#   ./deploy/setup.sh
#
# Creates: Artifact Registry repo, Firestore (Native) database, a Secret Manager
# secret for the AI Studio key, a least-privilege service account, then deploys
# to Cloud Run with Cloud Build.
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"           # Mumbai — keeps claim data in India
SERVICE="${SERVICE:-claimsaathi}"
SA="${SERVICE}-sa@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

gcloud config set project "$PROJECT_ID" >/dev/null

echo "▸ Enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com firestore.googleapis.com \
  aiplatform.googleapis.com generativelanguage.googleapis.com

echo "▸ Artifact Registry"
gcloud artifacts repositories describe "$SERVICE" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$SERVICE" --repository-format=docker --location="$REGION"

echo "▸ Firestore (Native mode)"
gcloud firestore databases describe --database='(default)' >/dev/null 2>&1 || \
  gcloud firestore databases create --location="$REGION" --type=firestore-native

echo "▸ Service account"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SERVICE}-sa" --display-name="ClaimSaathi runtime"
for role in roles/datastore.user roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" \
    --role="$role" --condition=None >/dev/null
done

echo "▸ Secret Manager: gemini-api-key"
if [[ -z "${GEMINI_API_KEY:-}" ]] && ! gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
  echo "GEMINI_API_KEY is not set and no gemini-api-key secret exists." >&2
  echo "Get a key at https://aistudio.google.com/apikey and re-run." >&2
  exit 1
fi
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  if gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
  else
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- \
      --replication-policy=user-managed --locations="$REGION"
  fi
fi
gcloud secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:$SA" \
  --role=roles/secretmanager.secretAccessor >/dev/null

echo "▸ Let Cloud Build deploy as the runtime service account"
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for member in "serviceAccount:$CB_SA" "serviceAccount:$COMPUTE_SA"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$member" \
    --role=roles/run.admin --condition=None >/dev/null || true
  gcloud iam service-accounts add-iam-policy-binding "$SA" --member="$member" \
    --role=roles/iam.serviceAccountUser >/dev/null || true
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$member" \
    --role=roles/artifactregistry.writer --condition=None >/dev/null || true
done

echo "▸ Build and deploy"
gcloud builds submit --config cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_SERVICE=${SERVICE},_REPO=${SERVICE}"

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
echo "✔ Deployed: $URL"
