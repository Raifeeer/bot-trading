# Contrato externo de Alpaca para lifecycle MLeg — 26 de agosto de 2026

## Hechos verificados

La documentación oficial de Alpaca describe las órdenes multi-pata de opciones como una única orden combinada con `order_class: "mleg"`, `qty`, `type`, `time_in_force`, `limit_price` y un arreglo `legs`. Cada pata contiene `symbol`, `ratio_qty`, `side` y `position_intent` (`buy_to_open`, `sell_to_open`, `buy_to_close`, `sell_to_close`). La petición admite entre 2 y 4 patas para opciones y la API devuelve una orden padre con las patas anidadas cuando se consulta con `nested=true`.

Para una orden MLeg de límite, Alpaca especifica que el precio positivo representa un débito y el negativo un crédito. La documentación de opciones indica que las órdenes de opciones admiten `market` y `limit`, y `time_in_force=day`; no se debe asumir que una orden MLeg GTC sea válida para este flujo.

La API del SDK instalado (`alpaca-py` compatible con `alpaca.trading.requests`) expone `OptionLegRequest`, `LimitOrderRequest`, `MarketOrderRequest`, `OrderClass.MLEG`, `PositionIntent` y `TradingClient.get_order_by_client_id()`. `GetOrdersRequest(nested=True)` y `GetOrderByIdRequest(nested=True)` permiten recuperar la estructura padre/patas.

## Consecuencia para Polaris

El executor anterior enviaba cada pata mediante `submit_option_order()` en un bucle secuencial. Esa ruta se elimina para spreads. Polaris debe construir y enviar una sola petición MLeg, persistir el ID padre y tratar cualquier respuesta no confirmada como `submission_unknown`, bloqueando nuevas entradas y evitando reintentos automáticos. Un estado `filled` del padre tampoco sustituye la reconciliación de posiciones: la posición se considera gestionable solo cuando las cantidades de todas las patas visibles en Alpaca coinciden con el contrato local.

## Fuentes

1. https://docs.alpaca.markets/us/docs/options-level-3-trading — Options Level 3 Trading, actualización visible 2025-09-24.
2. https://docs.alpaca.markets/us/reference/postorder — Create an Order, contrato OpenAPI visible con actualización 2026-05-27.
3. https://docs.alpaca.markets/us/docs/options-trading-overview — Options Trading Overview, actualización visible 2026-07-09.
