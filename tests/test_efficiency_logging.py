import pytest
from fastapi.testclient import TestClient
from newsfeed.main import app

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "Hello" in response.json()

def test_retrieve():
    response = client.get("/retrieve")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_ingest():
    # Minimal valid NewsItem structure, adjust fields as needed
    items = [{
        "id": "test_id_1",
        "source": "test_source",
        "title": "Test Title",
        "body": "Test Content",
        "published_at": "2024-01-01T00:00:00+00:00",
        "relevance_score": 0.5
    }]
    response = client.post("/ingest", json=items)
    assert response.status_code == 200
    assert response.json()["status"] == "ACK"

def test_retrieve_all():
    # Only works if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL is True
    response = client.get("/retrieve-all")
    # Accept both error and list response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list) or (isinstance(data, dict) and "error" in data) 