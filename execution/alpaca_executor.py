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
import hashlib
import logging
import math
import os
from datetime import datetime

from config import get_config

logger = logging.getLogger("execution")


def _field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _enum_value(value, default=""):
    return str(getattr(value, "value", value) or default)


def _finite_float(value, label):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Valor no numérico para {label}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ExecutionError(f"Valor no finito para {label}: {value!r}")
    return parsed


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
                   side=side, qty=qty, order_type=order_type, status=order.status,
                   id=str(getattr(order, "id", "") or ""),
                   client_order_id=str(getattr(
                       order, "client_order_id", "") or ""))
        self.order_log.append(rec)
        logger.info("Orden opción enviada: %s %d de %s (%s)", side, qty, contract_symbol, order.status)
        return rec

    @staticmethod
    def _normalize_order(order, reused: bool = False) -> dict:
        """Normaliza una orden simple o el padre MLeg y sus patas."""
        raw_legs = _field(order, "legs", None) or []
        legs = []
        symbols = []
        for leg in raw_legs:
            symbol = str(_field(leg, "symbol", "") or "")
            if symbol:
                symbols.append(symbol)
            legs.append({
                "id": str(_field(leg, "id", "") or ""),
                "symbol": symbol,
                "side": _enum_value(_field(leg, "side", "")),
                "qty": _finite_float(_field(leg, "qty", 0), "order leg qty"),
                "filled_qty": _finite_float(
                    _field(leg, "filled_qty", 0) or 0, "order leg filled_qty"),
                "ratio_qty": _finite_float(
                    _field(leg, "ratio_qty", 0) or 0, "order leg ratio_qty"),
                "status": _enum_value(_field(leg, "status", "")),
                "position_intent": _enum_value(
                    _field(leg, "position_intent", "")),
                "client_order_id": str(
                    _field(leg, "client_order_id", "") or ""),
            })
        primary_symbol = str(_field(order, "symbol", "") or "")
        if primary_symbol:
            symbols.insert(0, primary_symbol)
        unique_symbols = list(dict.fromkeys(symbols))
        return {
            "id": str(_field(order, "id", "") or ""),
            # Para compatibilidad con consumidores antiguos, symbol es la
            # primera pata si el padre MLeg no tiene símbolo propio. `symbols`
            # contiene siempre toda la orden.
            "symbol": primary_symbol or (unique_symbols[0] if unique_symbols else ""),
            "symbols": unique_symbols,
            "side": _enum_value(_field(order, "side", "")),
            "qty": _finite_float(_field(order, "qty", 0) or 0, "order qty"),
            "filled_qty": _finite_float(
                _field(order, "filled_qty", 0) or 0, "order filled_qty"),
            "status": _enum_value(_field(order, "status", "")),
            "position_intent": _enum_value(
                _field(order, "position_intent", "")),
            "client_order_id": str(
                _field(order, "client_order_id", "") or ""),
            "order_class": _enum_value(_field(order, "order_class", "simple"), "simple"),
            "order_type": _enum_value(
                _field(order, "type", None) or _field(order, "order_type", "")),
            "limit_price": _field(order, "limit_price", None),
            "legs": legs,
            "reused": bool(reused),
        }

    def _existing_order_by_client_id(self, client_order_id: str):
        """Busca una orden existente; solo un 404 autoriza a crear otra."""
        try:
            return self.trading.get_order_by_client_id(client_order_id)
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "status_code", None) == 404:
                return None
            raise ExecutionError(
                f"No se pudo verificar client_order_id {client_order_id}: {exc}") from exc

    @staticmethod
    def _default_mleg_client_order_id(specs: list[dict], order_type: str,
                                      time_in_force: str, closing: bool,
                                      limit_price: float | None) -> str:
        canonical = repr((
            [(str(s["symbol"]), str(s["side"]), int(s["qty"]),
              s.get("position_intent")) for s in specs],
            order_type, time_in_force, bool(closing), limit_price,
        ))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]
        return f"polaris-mleg-{digest}"

    def submit_spread(self, legs: list, time_in_force: str = "day",
                      order_type: str | None = None,
                      limit_price: float | None = None,
                      client_order_id: str | None = None,
                      closing: bool = False) -> dict:
        """Envía un spread como **una sola orden MLeg** de Alpaca.

        ``legs`` acepta dicts con ``symbol``, ``side``, ``qty``,
        ``limit_price`` y opcionalmente ``position_intent``. Las tuplas
        históricas ``(symbol, side, qty)`` también se aceptan. Nunca se hace
        fallback a envíos secuenciales: si el broker/SDK no puede construir la
        orden combinada, se lanza ``ExecutionError`` y el caller debe quedar
        fail-closed.
        """
        if not isinstance(legs, list) or not 2 <= len(legs) <= 4:
            raise ExecutionError("Una orden MLeg requiere entre 2 y 4 patas")
        if str(time_in_force).lower() != "day":
            raise ExecutionError(
                "Las órdenes MLeg de opciones se limitan a time_in_force=day")
        specs = []
        for item in legs:
            if isinstance(item, dict):
                spec = dict(item)
            else:
                try:
                    symbol, side, qty = item[:3]
                except (TypeError, ValueError) as exc:
                    raise ExecutionError(f"Pata MLeg inválida: {item!r}") from exc
                spec = {"symbol": symbol, "side": side, "qty": qty}
            symbol = str(spec.get("symbol", "") or "")
            side = str(spec.get("side", "") or "").lower()
            if not symbol or side not in {"buy", "sell"}:
                raise ExecutionError(f"Pata MLeg inválida: {spec!r}")
            try:
                qty_float = float(spec.get("qty", 0))
            except (TypeError, ValueError) as exc:
                raise ExecutionError(f"Cantidad MLeg inválida: {spec!r}") from exc
            if not math.isfinite(qty_float) or qty_float <= 0 or not qty_float.is_integer():
                raise ExecutionError(f"Cantidad MLeg debe ser entero positivo: {spec!r}")
            normalized = dict(spec)
            normalized.update({"symbol": symbol, "side": side, "qty": int(qty_float)})
            specs.append(normalized)

        parent_qty = 0
        for spec in specs:
            parent_qty = math.gcd(parent_qty, abs(int(spec["qty"])))
        if parent_qty <= 0:
            raise ExecutionError("La cantidad común de la orden MLeg debe ser positiva")
        ratios = [int(spec["qty"]) // parent_qty for spec in specs]
        if math.gcd(*ratios) != 1:
            raise ExecutionError("Las ratios MLeg no están simplificadas")
        if len({spec["symbol"] for spec in specs}) != len(specs):
            raise ExecutionError("Las patas MLeg deben tener símbolos distintos")

        requested_type = order_type or specs[0].get("order_type") or "limit"
        requested_type = str(requested_type).lower()
        if requested_type not in {"limit", "market"}:
            raise ExecutionError(f"Tipo no permitido para MLeg: {requested_type}")
        if any((spec.get("order_type") or requested_type).lower() != requested_type
               for spec in specs):
            raise ExecutionError("Todas las patas MLeg deben compartir order_type")

        net_limit = limit_price
        if requested_type == "limit" and net_limit is None:
            net_limit = 0.0
            for ratio, spec in zip(ratios, specs, strict=True):
                leg_price = spec.get("limit_price")
                if leg_price is None:
                    raise ExecutionError(
                        f"Falta precio límite para la pata MLeg {spec['symbol']}")
                leg_price = _finite_float(leg_price, f"limit_price {spec['symbol']}")
                if leg_price <= 0:
                    raise ExecutionError(
                        f"Precio límite inválido para la pata MLeg {spec['symbol']}")
                net_limit += leg_price * ratio * (1 if spec["side"] == "buy" else -1)
            net_limit = round(net_limit, 2)
        if requested_type == "limit":
            net_limit = _finite_float(net_limit, "MLeg limit_price")

        if client_order_id is None:
            client_order_id = self._default_mleg_client_order_id(
                specs, requested_type, time_in_force, closing, net_limit)
        client_order_id = str(client_order_id)
        if not client_order_id or len(client_order_id) > 128:
            raise ExecutionError("client_order_id MLeg vacío o demasiado largo")

        position_intents = {
            ("buy", False): "buy_to_open", ("sell", False): "sell_to_open",
            ("buy", True): "buy_to_close", ("sell", True): "sell_to_close",
        }
        request_legs = []
        for ratio, spec in zip(ratios, specs, strict=True):
            intent = str(spec.get("position_intent") or
                         position_intents[(spec["side"], bool(closing))]).lower()
            if intent not in {"buy_to_open", "sell_to_open",
                              "buy_to_close", "sell_to_close"}:
                raise ExecutionError(f"position_intent MLeg inválido: {intent}")
            request_legs.append({
                "symbol": spec["symbol"],
                "ratio_qty": ratio,
                "side": spec["side"],
                "position_intent": intent,
            })

        requested = {
            "ts": datetime.utcnow().isoformat(), "type": "spread",
            "order_class": "mleg", "qty": parent_qty,
            "limit_price": net_limit, "time_in_force": time_in_force,
            "client_order_id": client_order_id, "legs": request_legs,
            "reused": False,
        }
        if self.dry_run:
            requested["status"] = "DRY_RUN"
            self.order_log.append(requested)
            return requested

        existing = self._existing_order_by_client_id(client_order_id)
        if existing is not None:
            record = self._normalize_order(existing, reused=True)
            if record["status"] in {
                "canceled", "rejected", "expired", "replaced", "failed",
            }:
                raise ExecutionError(
                    f"client_order_id {client_order_id} ya terminó en "
                    f"estado {record['status']}; no se reenvía")
            record.update({
                "ts": datetime.utcnow().isoformat(), "type": "spread",
                "order_class": "mleg", "requested_qty": parent_qty,
                "requested_limit_price": net_limit,
                "request_legs": request_legs,
            })
            self.order_log.append(record)
            logger.warning("MLeg idempotente reutilizada: %s estado=%s",
                           client_order_id, record.get("status"))
            return record

        from alpaca.trading.enums import (OrderClass, OrderSide, PositionIntent,
                                          TimeInForce)
        from alpaca.trading.requests import (LimitOrderRequest,
                                             MarketOrderRequest,
                                             OptionLegRequest)
        try:
            tif = TimeInForce(time_in_force.lower())
        except ValueError as exc:
            raise ExecutionError(
                f"time_in_force no permitido para MLeg: {time_in_force}") from exc
        leg_requests = [OptionLegRequest(
            symbol=leg["symbol"], ratio_qty=leg["ratio_qty"],
            side=OrderSide(leg["side"]),
            position_intent=PositionIntent(leg["position_intent"]),
        ) for leg in request_legs]
        request_kwargs = {
            "qty": parent_qty,
            "time_in_force": tif,
            "order_class": OrderClass.MLEG,
            "legs": leg_requests,
            "client_order_id": client_order_id,
        }
        request_cls = MarketOrderRequest
        if requested_type == "limit":
            request_cls = LimitOrderRequest
            request_kwargs["limit_price"] = net_limit
        try:
            order = self.trading.submit_order(request_cls(**request_kwargs))
        except Exception as exc:  # noqa: BLE001
            raise ExecutionError(
                f"Falló el envío de orden MLeg {client_order_id}: {exc}") from exc
        record = self._normalize_order(order)
        record.update({
            "ts": datetime.utcnow().isoformat(), "type": "spread",
            "order_class": "mleg", "requested_qty": parent_qty,
            "requested_limit_price": net_limit, "request_legs": request_legs,
        })
        self.order_log.append(record)
        logger.info("Orden MLeg enviada: %s qty=%d estado=%s patas=%d",
                    client_order_id, parent_qty, record.get("status"), len(request_legs))
        return record

    def open_orders(self, symbols: list[str] | None = None) -> list:
        """Devuelve órdenes abiertas normalizadas para idempotencia de salidas.

        Alpaca es la fuente de verdad de órdenes pendientes; el filesystem local
        puede reiniciarse y no debe provocar reenvíos de una misma salida.
        """
        if self.trading is None:
            return []
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        request = GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            limit=500,
            # nested=True devuelve el padre MLeg y sus patas; consultar sin
            # filtro de símbolos evita perder un padre cuyo symbol sea vacío.
            nested=True,
        )
        orders = self.trading.get_orders(filter=request)
        if isinstance(orders, dict):
            raise ExecutionError(
                "Respuesta no normalizable de Alpaca al leer órdenes abiertas")
        result = []
        for order in orders:
            record = self._normalize_order(order)
            if symbols and not set(symbols).intersection(record["symbols"]):
                continue
            result.append(record)
        return result

    def order_statuses(self, order_ids: list[str]) -> list:
        """Consulta estados de órdenes concretas para reconciliar fills parciales."""
        if self.trading is None:
            return []
        from alpaca.trading.requests import GetOrderByIdRequest
        result = []
        for order_id in order_ids:
            try:
                try:
                    order = self.trading.get_order_by_id(
                        order_id, filter=GetOrderByIdRequest(nested=True))
                except TypeError:
                    # Dobles de tests/SDK antiguo sin parámetro filter.
                    order = self.trading.get_order_by_id(order_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("No se pudo consultar orden %s: %s", order_id, exc)
                result.append({
                    "id": str(order_id), "status": "lookup_error",
                    "error": str(exc),
                })
                continue
            result.append(self._normalize_order(order))
        return result

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
