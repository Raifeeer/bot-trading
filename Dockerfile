# Polaris Options Bot — imagen para Cloud Run
# El bot corre como proceso largo (loop con polling). Cloud Run con
# timeout >= 24h y siempre-activo mantiene el proceso vivo.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Dependencias de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-cloud-firestore

COPY config/ config/
COPY data/ data/
COPY strategies/ strategies/
COPY options/ options/
COPY risk/ risk/
COPY engine/ engine/
COPY execution/ execution/
COPY state/ state/
COPY bot.py .

# Un servidor HTTP mínimo para que Cloud Run reciba health-checks
# (el bot ignora peticiones; responde 200 con su estado).
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
