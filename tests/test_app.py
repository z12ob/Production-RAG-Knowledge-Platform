from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app


def test_application_imports_as_fastapi_instance() -> None:
    assert isinstance(app, FastAPI)


def test_root_redirects_to_interactive_documentation() -> None:
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
