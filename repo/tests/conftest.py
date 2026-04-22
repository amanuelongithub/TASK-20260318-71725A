import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    # Globally patch SessionLocal and engine to point to our test DB
    with patch("app.db.session.engine", engine), \
         patch("app.db.session.SessionLocal", TestingSessionLocal):
        Base.metadata.create_all(bind=engine)
        yield
        Base.metadata.drop_all(bind=engine)
    
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
    yield session
    session.close()
    # Explicitly clear all data between tests for isolation
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()

@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    # Compliance: Middleware requires HTTPS. We provide the header to simulate an SSL-terminating proxy.
    with TestClient(app, headers={"X-Forwarded-Proto": "https"}) as c:
        yield c
    app.dependency_overrides.clear()
