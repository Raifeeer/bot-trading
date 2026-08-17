"""_handle_message debe avisar de inmediato ("estoy analizando...") antes
de la parte lenta (fundamentales + análisis técnico + LLM), para que el
usuario sepa que el mensaje llegó mientras espera 30-60s por la respuesta
real. Sin red real: se mockean _send y _ai_answer_with_timeout."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state import telegram_bot  # noqa: E402


class TestTelegramAckMessage(unittest.TestCase):
    def test_sends_ack_before_slow_ai_call(self):
        calls_order = []

        def fake_send(text):
            calls_order.append(("send", text))
            return True

        def fake_ai_answer(text):
            calls_order.append(("ai_answer", text))
            return "respuesta simulada"

        with patch.object(telegram_bot, "_send", side_effect=fake_send), \
             patch.object(telegram_bot, "_ai_answer_with_timeout",
                          side_effect=fake_ai_answer):
            telegram_bot._handle_message("qué opinas de AAPL")

        self.assertGreaterEqual(len(calls_order), 2)
        self.assertEqual(calls_order[0][0], "send")
        self.assertIn("analizando", calls_order[0][1].lower())
        self.assertEqual(calls_order[1], ("ai_answer", "qué opinas de AAPL"))
        # La respuesta final tambien se envia (segundo _send)
        self.assertEqual(calls_order[-1][0], "send")

    def test_known_command_does_not_send_ack(self):
        calls_order = []

        def fake_send(text):
            calls_order.append(text)
            return True

        with patch.object(telegram_bot, "_send", side_effect=fake_send), \
             patch.object(telegram_bot, "_cmd_estado", return_value="estado ok"):
            telegram_bot._handle_message("/estado")

        self.assertEqual(len(calls_order), 1)
        self.assertNotIn("analizando", calls_order[0].lower())


if __name__ == "__main__":
    unittest.main()
