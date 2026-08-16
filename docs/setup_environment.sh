#!/usr/bin/env bash
# Script de configuración del Environment (claude.ai/code) para el proyecto
# bot-trading. Se ejecuta automáticamente en CADA contenedor nuevo, así que
# deja la sesión lista con acceso a GCP desde el primer turno, sin depender
# de que alguien vuelva a subir la keyfile a mano.
#
# Requiere que, en la configuración del Environment, exista una variable de
# entorno / secret llamada GCP_SA_KEY_JSON con el contenido completo del
# JSON de la cuenta de servicio (claude-trading-bot@gen-lang-client-0746441136).
set -euo pipefail

if [ -n "${GCP_SA_KEY_JSON:-}" ]; then
  mkdir -p /root/.gcp
  printf '%s' "$GCP_SA_KEY_JSON" > /root/.gcp/sa-key.json
  chmod 600 /root/.gcp/sa-key.json

  GCLOUD_BIN="$(command -v gcloud || echo /home/user/google-cloud-sdk-parent/google-cloud-sdk/bin/gcloud)"
  unset CLOUDSDK_AUTH_ACCESS_TOKEN || true
  "$GCLOUD_BIN" auth activate-service-account --key-file=/root/.gcp/sa-key.json
  "$GCLOUD_BIN" config set project gen-lang-client-0746441136

  # Persistir para shells posteriores dentro del mismo contenedor.
  {
    echo 'export PATH=$PATH:/home/user/google-cloud-sdk-parent/google-cloud-sdk/bin'
    echo 'unset CLOUDSDK_AUTH_ACCESS_TOKEN'
  } >> /root/.bashrc

  echo "[setup_environment] Autenticado como cuenta de servicio GCP."
else
  echo "[setup_environment] GCP_SA_KEY_JSON no está configurado en este Environment; sesión sin acceso a GCP." >&2
fi

pip install -q -r /home/user/bot-trading/requirements.txt || true
