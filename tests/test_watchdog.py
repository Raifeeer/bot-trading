import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot


class TestWatchdogUsesOsExit(unittest.TestCase):
    """Regresión: el watchdog corre en un hilo daemon secundario.

    sys.exit() lanza SystemExit, que el excepthook por defecto de threading
    ignora en silencio fuera del hilo principal: no mata el proceso ni los
    demás hilos, solo termina el propio hilo watchdog en silencio. Se
    reprodujo en vivo el 15 ago 2026 (Cloud Run, revisión polaris-bot-00058):
    el log CRITICAL "reiniciando el proceso" apareció, pero el proceso siguió
    corriendo. Solo os._exit() mata el proceso completo sin importar qué
    hilo lo invoque. Este test verifica el patrón por inspección de fuente en
    vez de invocar el watchdog real (os._exit() mataría el proceso del test).
    """

    def test_daemon_thread_exit_is_ignored_by_default(self):
        """Prueba de control: confirma el comportamiento real de Python que
        motiva este fix, para que el test no dependa de una suposición."""
        import threading
        import time

        result = {"main_alive_after": None}

        def _watchdog():
            time.sleep(0.05)
            sys.exit(1)  # el bug: esto NO mata el proceso

        threading.Thread(target=_watchdog, daemon=True).start()
        time.sleep(0.2)
        result["main_alive_after"] = True  # si sys.exit() matara el proceso,
        # esta línea nunca se alcanzaría
        self.assertTrue(result["main_alive_after"])

    def test_main_watchdog_uses_os_exit_not_sys_exit(self):
        src = inspect.getsource(bot.main)
        watchdog_src = src[src.index("def _watchdog()"):src.index("threading.Thread(target=_watchdog")]
        self.assertIn("os._exit(", watchdog_src)
        self.assertNotIn("sys.exit(", watchdog_src)
        self.assertNotIn("_sys.exit(", watchdog_src)


if __name__ == "__main__":
    unittest.main()
