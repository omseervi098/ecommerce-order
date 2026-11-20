import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MUG, INFUSER = 1, 5


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as c:
        yield c


def stock(client, product_id):
    return next(p["stock"] for p in client.get("/api/products").json() if p["id"] == product_id)


def place(client, *lines):
    return client.post("/api/orders", json={"items": [{"product_id": p, "qty": q} for p, q in lines]})


def test_api_place_order_success(client):
    res = place(client, (MUG, 2))
    assert res.status_code == 201
    assert res.json()["status"] == "PLACED"
    assert res.json()["ref"] == "ORD-0001"
    assert stock(client, MUG) == 3
    assert client.get("/api/orders/ORD-0001").json()["items"][0]["qty"] == 2


def test_api_insufficient_stock(client):
    res = place(client, (MUG, 2), (INFUSER, 1))
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "insufficient_stock"
    assert stock(client, MUG) == 5
    assert client.get("/api/orders").json() == []


def test_api_invalid_input(client):
    assert client.post("/api/orders", json={"items": []}).status_code == 422
    assert client.post("/api/orders", json={}).status_code == 422
    assert place(client, (MUG, 0)).status_code == 422


def test_api_invalid_transition(client):
    place(client, (MUG, 1))
    res = client.post("/api/orders/ORD-0001/status", json={"status": "SHIPPED"})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "invalid_transition"
    assert client.get("/api/orders/ORD-0001").json()["status"] == "PLACED"


def test_api_cancel_twice(client):
    place(client, (MUG, 2))
    first = client.post("/api/orders/ORD-0001/status", json={"status": "CANCELLED"})
    second = client.post("/api/orders/ORD-0001/status", json={"status": "CANCELLED"})
    assert first.status_code == 200
    assert second.status_code == 409
    assert stock(client, MUG) == 5


def test_unknown_status_value(client):
    place(client, (MUG, 1))
    res = client.post("/api/orders/ORD-0001/status", json={"status": "DELIVERED"})
    assert res.status_code == 422
    assert client.get("/api/orders?status=DELIVERED").status_code == 422


def test_ref_lookup_case_insensitive(client):
    place(client, (MUG, 1))
    assert client.get("/api/orders/ord-0001").status_code == 200


def test_unknown_order_404(client):
    assert client.get("/api/orders/ORD-9999").status_code == 404
    assert client.post("/api/orders/ORD-9999/status", json={"status": "PACKED"}).status_code == 404


def test_search_and_filter(client):
    place(client, (MUG, 1))
    place(client, (MUG, 1))
    client.post("/api/orders/ORD-0002/status", json={"status": "PACKED"})
    assert [o["ref"] for o in client.get("/api/orders?q=0001").json()] == ["ORD-0001"]
    assert [o["ref"] for o in client.get("/api/orders?status=PACKED").json()] == ["ORD-0002"]


def test_orders_survive_app_restart(db_path):
    with TestClient(create_app(db_path)) as first_run:
        place(first_run, (MUG, 2))

    with TestClient(create_app(db_path)) as second_run:
        assert second_run.get("/api/orders/ORD-0001").json()["status"] == "PLACED"
        assert stock(second_run, MUG) == 3


def test_index_page_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "<title>" in res.text


def test_importing_app_does_not_touch_default_database(tmp_path):
    import os
    import subprocess
    import sys

    target = tmp_path / "should-not-exist.db"
    env = {**os.environ, "ORDER_DB_PATH": str(target)}
    subprocess.run([sys.executable, "-c", "import app.main"], env=env, check=True)
    assert not target.exists()
