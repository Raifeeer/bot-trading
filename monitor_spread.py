#!/usr/bin/env python3
"""Monitor heredado de spreads deshabilitado.

Este archivo enviaba una segunda pata automáticamente después de detectar el
fill de una primera pata. Ese patrón no es admisible en Polaris: la ejecución
debe pasar por el executor validado, el ledger dedicado, RiskManager y los
controles PAPER. No se conserva ningún ID de orden ni credencial en código.
"""


def main() -> None:
    raise SystemExit(
        "monitor_spread.py está deshabilitado por seguridad; "
        "no consulta ni envía órdenes."
    )


if __name__ == "__main__":
    main()
