import pytest

from app.db import init_db, make_sessionmaker


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(make_sessionmaker(path))
    return path


@pytest.fixture
def session_factory(db_path):
    return make_sessionmaker(db_path)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s
