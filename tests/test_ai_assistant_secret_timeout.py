"""Regresión: _sm_key() debe pasar un timeout corto a Secret Manager.

Reproducido en vivo el 15 ago 2026: dos secretos de respaldo (Gemini, Grok)
sin permiso para la service account del bot tardaban 1-3 min en fallar
(reintentos por defecto de gRPC sobre PERMISSION_DENIED), bloqueando el
hilo de Telegram en el primer mensaje que usara el asistente de cada
proceso. Sin conexión real a GCP: se mockea el cliente de Secret Manager.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state import ai_assistant  # noqa: E402


class TestSecretManagerTimeout(unittest.TestCase):
    def test_sm_key_passes_explicit_timeout(self):
        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.payload.data.decode.return_value.strip.return_value = "clave"
        fake_client.access_secret_version.return_value = fake_response

        with patch.dict(os.environ, {"GCP_PROJECT_ID": "gen-lang-client-0746441136"}):
            with patch("google.cloud.secretmanager.SecretManagerServiceClient",
                       return_value=fake_client):
                ai_assistant._sm_key("cualquier-secreto")

        _, kwargs = fake_client.access_secret_version.call_args
        self.assertIn("timeout", kwargs)
        self.assertLessEqual(kwargs["timeout"], 10.0)

    def test_sm_key_without_project_never_calls_secret_manager(self):
        fake_client = MagicMock()
        with patch.dict(os.environ, {"GCP_PROJECT_ID": ""}):
            with patch("google.cloud.secretmanager.SecretManagerServiceClient",
                       return_value=fake_client):
                result = ai_assistant._sm_key("cualquier-secreto")
        self.assertEqual(result, "")
        fake_client.access_secret_version.assert_not_called()


if __name__ == "__main__":
    unittest.main()
