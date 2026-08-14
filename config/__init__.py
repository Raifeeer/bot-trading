"""Gestión de configuración del bot."""
import os
import yaml

CONFIG_PATH = os.environ.get(
    "BOT_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml")
)


def reset_config():
    """Reinicia el caché global (útil en tests/backtests)."""
    global _cfg
    _cfg = None


def load_config(path=None):
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # PERFIL RETO $100→$200: si universo.universo_reto.active, se usa el
    # universo barato y los parámetros de estructura del reto.
    uni = cfg.get("universo", {}) or {}
    reto = uni.get("universo_reto") or {}
    if reto.get("active"):
        cfg["universo"]["tickers"] = reto["tickers"]
        cfg["universo"]["min_price"] = reto.get("min_price", uni.get("min_price", 5.0))
        cfg["universo"]["min_avg_volume"] = reto.get(
            "min_avg_volume", uni.get("min_avg_volume", 500_000))
    return cfg


# Instancia global perezosa
_cfg = None


def get_config():
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg
