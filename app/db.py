import argparse
import os
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKey, create_engine, event, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DEFAULT_DB_PATH = Path(os.environ.get("ORDER_DB_PATH", "data/store.db"))

SEED_PRODUCTS = [
    ("MUG-001", "Ceramic Mug", 1250, 5),
    ("TEA-002", "Earl Grey Tea (100g)", 899, 20),
    ("KTL-003", "Stovetop Kettle", 3499, 3),
    ("CUP-004", "Glass Tea Cup", 650, 12),
    ("INF-005", "Tea Infuser", 499, 0),
    ("TRY-006", "Bamboo Serving Tray", 2200, 8),
]


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0"), CheckConstraint("price_cents >= 0"))

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    price_cents: Mapped[int]
    stock: Mapped[int]


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str | None] = mapped_column(unique=True)
    status: Mapped[str]
    total_cents: Mapped[int]
    created_at: Mapped[str] = mapped_column(server_default=text("(datetime('now'))"))
    items: Mapped[list["OrderItem"]] = relationship(order_by="OrderItem.product_id")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("qty > 0"),)

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    qty: Mapped[int]
    unit_price_cents: Mapped[int]
    product: Mapped[Product] = relationship()


def make_sessionmaker(path: str | Path = DEFAULT_DB_PATH) -> sessionmaker[Session]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(engine, "begin")
    def on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return sessionmaker(engine)


def init_db(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        Base.metadata.create_all(session.get_bind())
        with session.begin():
            if not session.scalar(select(func.count(Product.id))):
                session.add_all(
                    Product(sku=sku, name=name, price_cents=price, stock=stock)
                    for sku, name, price, stock in SEED_PRODUCTS
                )


def reset_db(path: str | Path = DEFAULT_DB_PATH) -> None:
    Path(path).unlink(missing_ok=True)
    init_db(make_sessionmaker(path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialise or reset the order database.")
    parser.add_argument("--reset", action="store_true", help="wipe all orders and re-seed stock")
    args = parser.parse_args()
    if args.reset:
        reset_db()
        print(f"Database reset and seeded at {DEFAULT_DB_PATH}")
    else:
        init_db(make_sessionmaker())
        print(f"Database ready at {DEFAULT_DB_PATH}")
