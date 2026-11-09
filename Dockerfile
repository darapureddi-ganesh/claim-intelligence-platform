# Cloud Run image for ClaimSaathi (ClaimIQ + PolicyLens + VerdictLens + Google AI).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m spacy download en_core_web_sm

COPY . .
# Train the pilot scoring models at build time so cold starts stay fast.
RUN python -c "from src.claimiq.scoring.engine import XGBoostScoringEngine; XGBoostScoringEngine()"

RUN useradd --uid 10001 --no-create-home app && chown -R app /app
USER app

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn src.platform.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --ws-ping-interval 20"]
