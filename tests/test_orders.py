import threading

import pytest
from sqlalchemy import func, select

from app import orders
from app.db import Order, OrderItem, Product
from app.orders import InsufficientStock, InvalidOrder, InvalidTransition, OrderNotFound

A, B = 1, 5


def set_stock(session, product_id, stock):
    with session.begin():
        session.get(Product, product_id).stock = stock


def stock_of(session, product_id):
    with session.begin():
        return session.scalar(select(Product.stock).where(Product.id == product_id))


def price_of(session, product_id):
    with session.begin():
        return session.scalar(select(Product.price_cents).where(Product.id == product_id))


def count(session, model):
    with session.begin():
        return session.scalar(select(func.count()).select_from(model))


def test_place_order_success(session):
    stock1, stock2 = stock_of(session, 1), stock_of(session, 2)

    order = orders.place_order(session, [{"product_id": 1, "qty": 2}, {"product_id": 2, "qty": 1}])

    assert order["ref"] == "ORD-0001"
    assert order["status"] == "PLACED"
    assert order["total_cents"] == 2 * price_of(session, 1) + price_of(session, 2)
    assert order["allowed_next"] == ["CANCELLED", "PACKED"]
    assert [(i["product_id"], i["qty"]) for i in order["items"]] == [(1, 2), (2, 1)]
    assert stock_of(session, 1) == stock1 - 2
    assert stock_of(session, 2) == stock2 - 1


def test_insufficient_stock_rejects_whole_order(session):
    set_stock(session, A, 5)
    set_stock(session, B, 0)

    with pytest.raises(InsufficientStock) as exc:
        orders.place_order(session, [{"product_id": A, "qty": 2}, {"product_id": B, "qty": 1}])

    assert exc.value.extra["shortages"] == [
        {"product_id": B, "name": "Tea Infuser", "requested": 1, "available": 0}
    ]
    assert stock_of(session, A) == 5
    assert count(session, Order) == 0
    assert count(session, OrderItem) == 0


def test_duplicate_lines_are_merged(session):
    set_stock(session, A, 3)
    with pytest.raises(InsufficientStock):
        orders.place_order(session, [{"product_id": A, "qty": 2}, {"product_id": A, "qty": 2}])
    assert stock_of(session, A) == 3


@pytest.mark.parametrize(
    "items",
    [
        [],
        "not a list",
        [{"product_id": A, "qty": 0}],
        [{"product_id": A, "qty": -1}],
        [{"product_id": A, "qty": "2"}],
        [{"product_id": A, "qty": 1.5}],
        [{"product_id": A, "qty": True}],
        [{"qty": 1}],
    ],
)
def test_rejects_bad_quantities(session, items):
    before = stock_of(session, A)
    with pytest.raises(InvalidOrder):
        orders.place_order(session, items)
    assert stock_of(session, A) == before
    assert count(session, Order) == 0


def test_unknown_product_rejected(session):
    before = stock_of(session, A)
    with pytest.raises(InvalidOrder):
        orders.place_order(session, [{"product_id": A, "qty": 1}, {"product_id": 9999, "qty": 1}])
    assert stock_of(session, A) == before
    assert count(session, Order) == 0


def test_second_order_cannot_oversell(session):
    set_stock(session, A, 5)
    orders.place_order(session, [{"product_id": A, "qty": 3}])
    with pytest.raises(InsufficientStock):
        orders.place_order(session, [{"product_id": A, "qty": 3}])
    assert stock_of(session, A) == 2
    assert count(session, Order) == 1


def place(session, product_id=A, qty=2):
    return orders.place_order(session, [{"product_id": product_id, "qty": qty}])["ref"]


def test_full_happy_path(session):
    ref = place(session)
    assert orders.change_status(session, ref, "PACKED")["status"] == "PACKED"
    shipped = orders.change_status(session, ref, "SHIPPED")
    assert shipped["status"] == "SHIPPED"
    assert shipped["allowed_next"] == []


def test_cannot_skip_packed(session):
    ref = place(session)
    with pytest.raises(InvalidTransition):
        orders.change_status(session, ref, "SHIPPED")
    assert orders.get_order(session, ref)["status"] == "PLACED"


def test_cancel_restores_stock_exactly_once(session):
    set_stock(session, A, 5)
    ref = place(session, A, 2)
    assert stock_of(session, A) == 3

    orders.change_status(session, ref, "CANCELLED")
    assert stock_of(session, A) == 5

    with pytest.raises(InvalidTransition):
        orders.change_status(session, ref, "CANCELLED")
    assert stock_of(session, A) == 5


def test_cancel_from_packed_restores_stock(session):
    set_stock(session, A, 5)
    ref = place(session, A, 2)
    orders.change_status(session, ref, "PACKED")
    orders.change_status(session, ref, "CANCELLED")
    assert stock_of(session, A) == 5


def test_cannot_cancel_shipped(session):
    set_stock(session, A, 5)
    ref = place(session, A, 2)
    orders.change_status(session, ref, "PACKED")
    orders.change_status(session, ref, "SHIPPED")
    with pytest.raises(InvalidTransition):
        orders.change_status(session, ref, "CANCELLED")
    assert stock_of(session, A) == 3
    assert orders.get_order(session, ref)["status"] == "SHIPPED"


def test_change_status_unknown_ref(session):
    with pytest.raises(OrderNotFound):
        orders.change_status(session, "ORD-9999", "PACKED")


def test_unknown_status_rejected(session):
    ref = place(session)
    with pytest.raises(InvalidOrder):
        orders.change_status(session, ref, "DELIVERED")


def test_list_orders_search_and_filter(session):
    refs = [place(session, 2, 1) for _ in range(3)]
    orders.change_status(session, refs[1], "PACKED")

    assert [o["ref"] for o in orders.list_orders(session, q="0002")] == ["ORD-0002"]
    assert [o["ref"] for o in orders.list_orders(session, status="PACKED")] == ["ORD-0002"]
    assert [o["ref"] for o in orders.list_orders(session, q="ord")] == ["ORD-0003", "ORD-0002", "ORD-0001"]
    assert orders.list_orders(session)[0]["item_count"] == 1
    with pytest.raises(InvalidOrder):
        orders.list_orders(session, status="LOST")


@pytest.mark.parametrize(
    "items",
    [
        [{"product_id": 10**20, "qty": 1}],
        [{"product_id": A, "qty": 10**20}],
        [{"product_id": A, "qty": 1}] * 101,
    ],
)
def test_rejects_oversized_input(session, items):
    with pytest.raises(InvalidOrder):
        orders.place_order(session, items)


def test_concurrent_orders_for_last_units(session, session_factory):
    set_stock(session, A, 5)
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        with session_factory() as s:
            barrier.wait()
            try:
                orders.place_order(s, [{"product_id": A, "qty": 3}])
                results.append("ok")
            except InsufficientStock:
                results.append("short")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["ok", "short"]
    assert stock_of(session, A) == 2
