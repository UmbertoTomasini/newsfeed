import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsfeed.main import app

client = TestClient(app)
MAX_LATENCY_SECONDS = 10  # 10 seconds


def test_latency_retrieve():
    start = time.perf_counter()
    response = client.get("/retrieve")
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert (
        elapsed < MAX_LATENCY_SECONDS
    ), f"/retrieve latency {elapsed:.3f}s exceeded {MAX_LATENCY_SECONDS:.3f}s"


def test_latency_ingest():
    # Prepare a minimal valid NewsItem
    now = datetime.now(timezone.utc).isoformat()
    items = [
        {
            "id": "latency-test-1",
            "source": "latency-test",
            "title": "Latency Test Event",
            "body": "Synthetic event for latency test.",
            "published_at": now,
        }
    ]
    start = time.perf_counter()
    response = client.post("/ingest", json=items)
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert (
        elapsed < MAX_LATENCY_SECONDS
    ), f"/ingest latency {elapsed:.3f}s exceeded {MAX_LATENCY_SECONDS:.3f}s"


def test_latency_retrieve_all():
    # Only run if /retrieve-all is enabled
    start = time.perf_counter()
    response = client.get("/retrieve-all")
    elapsed = time.perf_counter() - start
    # /retrieve-all may be disabled if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL is False
    if response.status_code == 200:
        assert (
            elapsed < MAX_LATENCY_SECONDS
        ), f"/retrieve-all latency {elapsed:.3f}s exceeded {MAX_LATENCY_SECONDS:.3f}s"
    else:
        assert (
            response.status_code == 200
            or response.status_code == 422
            or response.status_code == 400
            or response.status_code == 404
            or response.status_code == 403
        )
