from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import orders
from app.db import DEFAULT_DB_PATH, init_db, make_sessionmaker

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    session_factory = make_sessionmaker(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(session_factory)
        yield

    app = FastAPI(title="Order Console", lifespan=lifespan)

    def get_session():
        with session_factory() as session:
            yield session

    @app.exception_handler(orders.OrderError)
    def handle_order_error(request: Request, exc: orders.OrderError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()})

    @app.get("/api/products")
    def list_products(session=Depends(get_session)):
        return orders.list_products(session)

    @app.post("/api/orders", status_code=201)
    def place_order(body: dict = Body(...), session=Depends(get_session)):
        return orders.place_order(session, body.get("items"))

    @app.get("/api/orders")
    def list_orders(q: str | None = None, status: str | None = None, session=Depends(get_session)):
        return orders.list_orders(session, q=q, status=status)

    @app.get("/api/orders/{ref}")
    def get_order(ref: str, session=Depends(get_session)):
        return orders.get_order(session, ref)

    @app.post("/api/orders/{ref}/status")
    def change_status(ref: str, body: dict = Body(...), session=Depends(get_session)):
        return orders.change_status(session, ref, body.get("status"))

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
