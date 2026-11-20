from sqlalchemy import func, select

from app.db import Product, init_db, make_sessionmaker


def test_seed_has_six_products_one_out_of_stock(session):
    stocks = session.scalars(select(Product.stock)).all()
    assert len(stocks) == 6
    assert stocks.count(0) == 1


def test_init_is_idempotent(session_factory, session):
    init_db(session_factory)
    assert session.scalar(select(func.count(Product.id))) == 6


def test_data_persists_after_reconnect(db_path):
    with make_sessionmaker(db_path)() as first, first.begin():
        first.get(Product, 1).stock = 3

    with make_sessionmaker(db_path)() as second:
        assert second.get(Product, 1).stock == 3
