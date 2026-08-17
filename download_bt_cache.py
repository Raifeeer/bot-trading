"""Descarga y cachea a disco el histórico diario para los backtests.

En la sandbox de Claude Code yfinance no funciona (curl_cffi vs proxy TLS),
así que se usa Alpaca con credenciales de Secret Manager. Se descarga una
sola vez y se guarda en un pickle para que las corridas posteriores sean
instantáneas y reproducibles (mismo dataset para todos los escenarios).
"""
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_alpaca_creds():
    from google.cloud import secretmanager
    c = secretmanager.SecretManagerServiceClient()
    base = "projects/173223792589/secrets"
    for env, secret in (("APCA_API_KEY_ID", "alpaca-key"),
                        ("APCA_API_SECRET_KEY", "alpaca-secret")):
        if not os.environ.get(env):
            v = c.access_secret_version(
                request={"name": f"{base}/{secret}/versions/latest"}, timeout=20.0)
            os.environ[env] = v.payload.data.decode().strip()


def main():
    days = int(os.environ.get("BT_DAYS", "900"))
    out_path = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    _load_alpaca_creds()

    from datetime import datetime, timedelta, timezone
    from data.feed import _alpaca_one
    from loop_backtests import SCENARIOS

    tickers = sorted({t for s in SCENARIOS.values() for t in s["tickers"]})
    # SPY/QQQ son necesarios como referencia de régimen aunque no estén en
    # todos los escenarios.
    for extra in ("SPY", "QQQ"):
        if extra not in tickers:
            tickers.append(extra)

    # El plan free de Alpaca rechaza el rango "recent SIP" (~últimos 2 días).
    # Se corta la ventana 3 días antes de hoy; yfinance (que cubriría ese
    # tramo) no funciona en esta sandbox. Se declara en el informe.
    now = datetime.now(timezone.utc)
    end = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"Descargando {start} -> {end} para {len(tickers)} tickers: {tickers}")
    t0 = time.time()
    data = {}
    for s in tickers:
        try:
            df = _alpaca_one(s, "1d", start, end)
            if df is not None and not df.empty:
                data[s] = df
            else:
                print(f"  {s}: vacío")
        except Exception as e:  # noqa: BLE001
            print(f"  {s}: FALLO {type(e).__name__} {str(e)[:100]}")
    print(f"Listo en {time.time()-t0:.0f}s — {len(data)}/{len(tickers)} con datos")

    for s, df in sorted(data.items()):
        if df is None or df.empty:
            print(f"  {s}: SIN DATOS")
        else:
            print(f"  {s}: {len(df)} barras  {df.index[0].date()} -> {df.index[-1].date()}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump(data, f)
    print(f"Cache escrito en {out_path}")


if __name__ == "__main__":
    main()
