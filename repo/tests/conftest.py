import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from app.main import app
from app.db.base import Base
from app.db.session import get_db

import tempfile
import os

# Use a named temporary file to ensure all connections share the same database
db_fd, db_path = tempfile.mkstemp()
SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _install_sqlite_test_triggers() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS validate_process_idempotency_sqlite_24h
            BEFORE INSERT ON process_instances
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'Persistence-layer violation: Duplicate business_id or idempotency_key within 24-hour window')
                WHERE EXISTS (
                    SELECT 1 FROM process_instances
                    WHERE org_id = NEW.org_id
                      AND (business_id = NEW.business_id OR idempotency_key = NEW.idempotency_key)
                      AND created_at >= datetime('now', '-24 hours')
                );
            END;
        """))

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    _install_sqlite_test_triggers()

    with patch("app.db.session.engine", engine), \
         patch("app.db.session.SessionLocal", TestingSessionLocal):
        yield
    
    # Disposal is required to release the file handle on Windows
    engine.dispose()
    
    # Cleanup the temp database file
    os.close(db_fd)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass # Non-fatal if we can't delete it immediately

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()

@pytest.fixture
def https_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, headers={"X-Forwarded-Proto": "https"}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def http_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client(https_client):
    yield https_client
