"""Ejecutor para Alpaca (paper y real): acciones y opciones.

Responsabilidades:
  - Conectar a Alpaca y validar estado de cuenta
  - Submitir órdenes de acciones y de contratos de opciones (OCC symbols)
  - Seguimiento de posiciones, P&L no realizado y equity
  - Modo dry-run: registra órdenes sin enviarlas (para validación segura)

Requisitos Alpaca para opciones:
  - Cuenta con opciones aprobadas (nivel 2+ para spreads)
  - Paper trading de opciones disponible en cuentas paper
"""
import logging
import os
from datetime import datetime

from config import get_config

logger = logging.getLogger("execution")


class ExecutionError(RuntimeError):
    pass


class AlpacaExecutor:
    def __init__(self, dry_run: bool = False):
        self.cfg = get_config()
        self.dry_run = dry_run or os.environ.get("BOT_DRY_RUN", "0") == "1"
        self.trading = None
        self.data = None
        self.order_log = []

    def connect(self):
        from alpaca.trading.client import TradingClient
        try:
            from alpaca.data.historical.stock import StockHistoricalDataClient as StockDataClient
        except ImportError:  # alpaca-py antiguo
            from alpaca.data.client import StockHistoricalDataClient as StockDataClient
        key = os.environ.get("APCA_API_KEY_ID") or self.cfg["broker"].get("api_key")
        secret = os.environ.get("APCA_API_SECRET_KEY") or self.cfg["broker"].get("secret_key")
        paper = self.cfg["broker"].get("paper", True)
        if not key or not secret:
            raise ExecutionError(
                "Faltan credenciales APCA_API_KEY_ID / APCA_API_SECRET_KEY. "
                "Crea tu cuenta en https://app.alpaca.markets y exportalas antes de correr el bot.")
        self.trading = TradingClient(key, secret, paper=paper)
        self.data = StockDataClient(api_key=key, secret_key=secret)
        acct = self.trading.get_account()
        logger.info("Alpaca conectado: status=%s, equity=%.2f, pattern_day_trader=%s, dry_run=%s",
                    acct.status, float(acct.equity), acct.pattern_day_trader, self.dry_run)
        return acct

    def account_snapshot(self) -> dict:
        if self.trading is None:
            return {
                "equity": float(self.cfg["broker"].get("sim_equity", 100_000.0)),
                "cash": float(self.cfg["broker"].get("sim_cash", 50_000.0)),
                "buying_power": float(self.cfg["broker"].get("sim_equity", 100_000.0)),
                "portfolio_value": float(self.cfg["broker"].get("sim_equity", 100_000.0)),
                "last_equity": float(self.cfg["broker"].get("sim_equity", 100_000.0)),
                "day_trade_count": 0,
                "status": "SIMULATED",
            }
        acct = self.trading.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(getattr(acct, "cash", 0.0) or 0.0),
            "buying_power": float(getattr(acct, "buying_power", 0.0) or 0.0),
            "portfolio_value": float(getattr(acct, "portfolio_value", acct.equity)),
            "last_equity": float(getattr(acct, "last_equity", acct.equity)),
            "day_trade_count": int(getattr(acct, "day_trade_count", 0) or 0),
            "status": str(getattr(acct, "status", "UNKNOWN")),
        }

    def submit_stock_order(self, symbol: str, side: str, qty: float,
                           order_type: str = "limit", limit_price: float = None,
                           time_in_force: str = "day") -> dict:
        """Orden de acciones. side: buy|sell, qty en acciones (fraccionarias ok)."""
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC
        if self.dry_run:
            rec = dict(ts=datetime.utcnow().isoformat(), type="stock", symbol=symbol,
                       side=side, qty=qty, order_type=order_type,
                       limit_price=limit_price, status="DRY_RUN")
            self.order_log.append(rec)
            logger.info("[DRY-RUN] orden acciones %s %s %.1f @ %s", side, symbol, qty, limit_price)
            return rec
        if order_type == "market":
            req = MarketOrderRequest(symbol=symbol, qty=qty,
                                     side=OrderSide(side), time_in_force=tif)
        else:
            if limit_price is None or float(limit_price) <= 0:
                raise ExecutionError(
                    f"Precio límite inválido para {symbol}: {limit_price!r}")
            req = LimitOrderRequest(symbol=symbol, qty=qty,
                                    side=OrderSide(side), time_in_force=tif,
                                    limit_price=float(limit_price))
        order = self.trading.submit_order(req)
        rec = dict(ts=datetime.utcnow().isoformat(), type="stock", symbol=symbol,
                   side=side, qty=qty, order_type=order_type, status=order.status)
        self.order_log.append(rec)
        logger.info("Orden acciones enviada: %s %s %.1f de %s (%s)", side, symbol, qty, symbol, order.status)
        return rec

    def submit_option_order(self, contract_symbol: str, side: str, qty: int,
                            order_type: str = "limit", limit_price: float = None,
                            time_in_force: str = "day") -> dict:
        """Orden de un contrato de opciones (símbolo OCC).
        qty en contratos; para spreads se envía una orden por pata (Alpaca
        soporta multi-leg vía Bracket/legged orders en plan Advanced).
        """
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC
        if self.dry_run:
            rec = dict(ts=datetime.utcnow().isoformat(), type="option", symbol=contract_symbol,
                       side=side, qty=qty, order_type=order_type,
                       limit_price=limit_price, status="DRY_RUN")
            self.order_log.append(rec)
            logger.info("[DRY-RUN] orden opción %s %s %d @ %s", side, contract_symbol, qty, limit_price)
            return rec
        # Las órdenes de opciones van al endpoint de opciones de Alpaca
        if order_type == "market":
            req = MarketOrderRequest(
                symbol=contract_symbol,
                qty=qty,
                side=OrderSide(side),
                time_in_force=tif,
            )
        else:
            if limit_price is None or float(limit_price) <= 0:
                raise ExecutionError(
                    f"Precio límite inválido para {contract_symbol}: {limit_price!r}")
            req = LimitOrderRequest(symbol=contract_symbol, qty=qty,
                                    side=OrderSide(side), time_in_force=tif,
                                    limit_price=float(limit_price))
        order = self.trading.submit_order(req)
        rec = dict(ts=datetime.utcnow().isoformat(), type="option", symbol=contract_symbol,
                   side=side, qty=qty, order_type=order_type, status=order.status)
        self.order_log.append(rec)
        logger.info("Orden opción enviada: %s %d de %s (%s)", side, qty, contract_symbol, order.status)
        return rec

    def submit_spread(self, legs: list, time_in_force: str = "day") -> dict:
        """Orden multi-leg (spread) con precio límite neto.
        legs: lista de (contract_symbol, side[buy|sell], ratio).
        """
        if self.dry_run:
            rec = dict(ts=datetime.utcnow().isoformat(), type="spread", legs=legs,
                       status="DRY_RUN")
            self.order_log.append(rec)
            return rec
        # Nota: Alpaca soporta órdenes legged vía endpoint de opciones; el SDK
        # expone submit_order para cada pata individualmente. Para ejecución
        # sincronizada del spread se recomienda enviar ambas patas y verificar
        # fills (fallback implementado por patas secuenciales):
        results = []
        for s, side, ratio in legs:
            for _ in range(ratio):
                results.append(self.submit_option_order(s, side, 1,
                                                        time_in_force=time_in_force))
        return dict(ts=datetime.utcnow().isoformat(), type="spread", legs=legs,
                    results=results)

    def positions(self) -> list:
        out = []
        for p in self.trading.get_all_positions():
            out.append(dict(symbol=p.symbol, qty=float(p.qty),
                            avg_entry=float(p.avg_entry_price),
                            market_value=float(p.market_value),
                            unrealized_pl=float(p.unrealized_pl),
                            unrealized_pl_pct=float(p.unrealized_plpc),
                            asset_class=getattr(p, "asset_class", None)))
        return out

    def cancel_all(self):
        if self.dry_run:
            logger.info("[DRY-RUN] cancel_all ignorado")
            return
        self.trading.cancel_orders()
