from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import Order, OrderItem, Product

STATUSES = ("PLACED", "PACKED", "SHIPPED", "CANCELLED")

TRANSITIONS: dict[str, set[str]] = {
    "PLACED": {"PACKED", "CANCELLED"},
    "PACKED": {"SHIPPED", "CANCELLED"},
    "SHIPPED": set(),
    "CANCELLED": set(),
}


class OrderError(Exception):
    status_code = 400
    code = "order_error"

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra

    def to_detail(self) -> dict:
        return {"error": self.code, "message": self.message, **self.extra}


class InvalidOrder(OrderError):
    status_code = 422
    code = "invalid_order"


class InsufficientStock(OrderError):
    status_code = 409
    code = "insufficient_stock"


class OrderNotFound(OrderError):
    status_code = 404
    code = "order_not_found"


class InvalidTransition(OrderError):
    status_code = 409
    code = "invalid_transition"


def _order_dict(order: Order) -> dict:
    return {
        "ref": order.ref,
        "status": order.status,
        "total_cents": order.total_cents,
        "created_at": order.created_at,
        "allowed_next": sorted(TRANSITIONS[order.status]),
        "items": [
            {
                "product_id": item.product_id,
                "sku": item.product.sku,
                "name": item.product.name,
                "qty": item.qty,
                "unit_price_cents": item.unit_price_cents,
                "line_total_cents": item.qty * item.unit_price_cents,
            }
            for item in order.items
        ],
    }


def _find_order(session: Session, ref: str) -> Order:
    ref = ref.strip().upper()
    order = session.scalar(select(Order).where(Order.ref == ref))
    if order is None:
        raise OrderNotFound(f"Order {ref} not found")
    return order


def _check_status(status) -> None:
    if status not in STATUSES:
        raise InvalidOrder(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}")


def list_products(session: Session) -> list[dict]:
    with session.begin():
        products = session.scalars(select(Product).order_by(Product.id))
        return [
            {"id": p.id, "sku": p.sku, "name": p.name, "price_cents": p.price_cents, "stock": p.stock}
            for p in products
        ]


def get_order(session: Session, ref: str) -> dict:
    with session.begin():
        return _order_dict(_find_order(session, ref))


MAX_LINES = 100
MAX_QTY = 10_000
MAX_ID = 2**63 - 1


def _validate_items(items) -> dict[int, int]:
    if not isinstance(items, list) or not items:
        raise InvalidOrder("An order needs at least one item")
    if len(items) > MAX_LINES:
        raise InvalidOrder(f"An order can have at most {MAX_LINES} lines")

    def is_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    wanted: dict[int, int] = {}
    for item in items:
        product_id = item.get("product_id") if isinstance(item, dict) else None
        if not is_int(product_id) or not 1 <= product_id <= MAX_ID:
            raise InvalidOrder("Each item needs a positive integer product_id")
        qty = item.get("qty")
        if not is_int(qty) or not 1 <= qty <= MAX_QTY:
            raise InvalidOrder(f"Each item needs a whole-number qty between 1 and {MAX_QTY}")
        wanted[item["product_id"]] = wanted.get(item["product_id"], 0) + qty
    return wanted


def place_order(session: Session, items: list[dict]) -> dict:
    wanted = _validate_items(items)

    with session.begin():
        products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(wanted)))}

        unknown = sorted(set(wanted) - set(products))
        if unknown:
            raise InvalidOrder(f"Unknown product id(s): {unknown}", unknown_product_ids=unknown)

        shortages = [
            {"product_id": pid, "name": products[pid].name,
             "requested": qty, "available": products[pid].stock}
            for pid, qty in sorted(wanted.items())
            if qty > products[pid].stock
        ]
        if shortages:
            names = ", ".join(f"{s['name']} (requested {s['requested']}, available {s['available']})"
                              for s in shortages)
            raise InsufficientStock(f"Not enough stock: {names}", shortages=shortages)

        order = Order(
            status="PLACED",
            total_cents=sum(products[pid].price_cents * qty for pid, qty in wanted.items()),
        )
        session.add(order)
        session.flush()
        order.ref = f"ORD-{order.id:04d}"

        for pid, qty in wanted.items():
            products[pid].stock -= qty
            session.add(OrderItem(order_id=order.id, product_id=pid, qty=qty,
                                  unit_price_cents=products[pid].price_cents))
        ref = order.ref

    return get_order(session, ref)


def list_orders(session: Session, q: str | None = None, status: str | None = None) -> list[dict]:
    query = select(Order).options(selectinload(Order.items)).order_by(Order.id.desc())
    if q:
        query = query.where(Order.ref.ilike(f"%{q.strip()}%"))
    if status:
        _check_status(status)
        query = query.where(Order.status == status)

    with session.begin():
        return [
            {"ref": o.ref, "status": o.status, "total_cents": o.total_cents,
             "created_at": o.created_at, "item_count": len(o.items)}
            for o in session.scalars(query)
        ]


def change_status(session: Session, ref: str, new_status: str) -> dict:
    _check_status(new_status)

    with session.begin():
        order = _find_order(session, ref)
        current = order.status
        if new_status not in TRANSITIONS[current]:
            raise InvalidTransition(
                f"Cannot change order {order.ref} from {current} to {new_status}",
                current_status=current,
                allowed_next=sorted(TRANSITIONS[current]),
            )

        order.status = new_status
        if new_status == "CANCELLED":
            for item in order.items:
                item.product.stock += item.qty
        result = _order_dict(order)

    return result
