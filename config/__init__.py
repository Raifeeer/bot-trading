"""Gestión de configuración del bot."""
import os
import yaml

CONFIG_PATH = os.environ.get(
    "BOT_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml")
)


def load_config(path=None):
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Instancia global perezosa
_cfg = None


def get_config():
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg
