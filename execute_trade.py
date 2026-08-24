#!/usr/bin/env python3
"""Script de ejecución heredado deshabilitado.

Este archivo contenía una prueba multi-pata con parámetros antiguos y
credenciales literales. No debe volver a utilizarse: la ejecución de Polaris
pasa exclusivamente por el executor validado, RiskManager, el ledger dedicado
y los controles PAPER de Cloud Run.
"""


def main() -> None:
    raise SystemExit(
        "execute_trade.py está deshabilitado por seguridad; "
        "no ejecuta órdenes. Use el flujo PAPER autorizado y auditado."
    )


if __name__ == "__main__":
    main()
