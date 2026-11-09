#!/usr/bin/env bash
# Optional: switch the running service from the AI Studio key to Vertex AI
# (service-account auth, no key). Gemma then needs a self-hosted endpoint
# (GEMMA_ENDPOINT), because Gemma on Vertex is served from Model Garden.
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-claimsaathi}"
gcloud run services update "$SERVICE" --region="$REGION" --project="$PROJECT_ID" \
  --remove-secrets=GEMINI_API_KEY \
  --update-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global,LIVE_LOCATION=us-central1,GEMINI_LIVE_MODEL=${GEMINI_LIVE_MODEL:-gemini-live-2.5-flash-native-audio}${GEMMA_ENDPOINT:+,GEMMA_ENDPOINT=$GEMMA_ENDPOINT}"
