# Order Console

Browser console for phone orders: create orders from a live catalogue, find them by
reference or status, and move them through Placed → Packed → Shipped (or Cancelled).
FastAPI + SQLAlchemy + SQLite, plain HTML/JS front end.

## Run

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m app.db --reset      # seed / wipe data (also auto-seeds on first start)
uv run uvicorn app.main:app --reload # http://127.0.0.1:8000
uv run pytest -v
```

Data lives in `data/store.db` (override with `ORDER_DB_PATH`). The seed has 6 products;
Ceramic Mug (stock 5) and Tea Infuser (stock 0) are products A and B from the brief.

## Rules (enforced on the server)

- An order is placed only if every line is in stock; otherwise nothing changes (409).
- Stock is deducted on placement and restored exactly once on cancellation.
- Only Placed → Packed → Shipped, and cancel from Placed or Packed; anything else is 409.
- Every transaction starts with `BEGIN IMMEDIATE`, so concurrent orders can't oversell.

All rules live in `app/orders.py`; `app/main.py` only maps them to HTTP.

## API

| Method | Path | Body |
|---|---|---|
| GET | `/api/products` | |
| POST | `/api/orders` | `{"items": [{"product_id": 1, "qty": 2}]}` |
| GET | `/api/orders?q=&status=` | |
| GET | `/api/orders/{ref}` | |
| POST | `/api/orders/{ref}/status` | `{"status": "PACKED"}` |
# ecommerce-order
