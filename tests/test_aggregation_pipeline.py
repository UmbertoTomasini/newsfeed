from fastapi.testclient import TestClient
from newsfeed.main import app, accepted_items, accepted_item_ids # Import global state
from newsfeed.models import NewsItem
from datetime import datetime, timezone
import pytest
from fastapi.encoders import jsonable_encoder # Import jsonable_encoder
from newsfeed.ingestion.manager import IngestionManager
from newsfeed.ingestion.mock_source_data import MockSource

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_data_before_each_test():
    """Clears the in-memory store before each test to ensure isolation."""
    accepted_items.clear()
    accepted_item_ids.clear()

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"Hello": "World"}

def test_ingest_news():
    test_items = [
        NewsItem(
            id="ingest-test-1",
            source="manual-ingest",
            title="Test Ingested Item 1",
            body="This is a manually ingested test item.",
            published_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="ingest-test-2",
            source="manual-ingest",
            title="Test Ingested Item 2",
            body="Another manually ingested test item.",
            published_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        )
    ]
    response = client.post("/ingest", json=jsonable_encoder([item.model_dump(mode='json') for item in test_items]))
    assert response.status_code == 200
    assert response.json() == {"status": "ACK"}
    assert len(accepted_items) == 2
    assert "ingest-test-1" in accepted_item_ids

def test_retrieve_news_sorted_by_recency():
    # Ingest items out of order to check sorting
    test_items = [
        NewsItem(
            id="retrieve-test-1", source="test-source", title="Oldest", body="",
            published_at=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="retrieve-test-2", source="test-source", title="Newest", body="",
            published_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="retrieve-test-3", source="test-source", title="Middle", body="",
            published_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        )
    ]
    client.post("/ingest", json=jsonable_encoder([item.model_dump(mode='json') for item in test_items]))

    response = client.get("/retrieve")
    assert response.status_code == 200
    retrieved_items = [NewsItem(**item_data) for item_data in response.json()] # Convert back to NewsItem objects
    
    # Verify sorting: Newest, Middle, Oldest
    assert retrieved_items[0].id == "retrieve-test-2"
    assert retrieved_items[1].id == "retrieve-test-3"
    assert retrieved_items[2].id == "retrieve-test-1"

def test_deduplication():
    item = NewsItem(
        id="dup-test-1", source="test-source", title="Original", body="",
        published_at=datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )
    client.post("/ingest", json=jsonable_encoder([item.model_dump(mode='json')]))
    assert len(accepted_items) == 1
    assert "dup-test-1" in accepted_item_ids

    # Try to ingest the same item again
    duplicate_item = NewsItem(
        id="dup-test-1", source="test-source", title="Duplicate", body="", # Same ID
        published_at=datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )
    response = client.post("/ingest", json=jsonable_encoder([duplicate_item.model_dump(mode='json')]))
    assert response.status_code == 200
    assert response.json() == {"status": "ACK"}
    
    # Verify that the total count of accepted_items has not increased
    assert len(accepted_items) == 1
    assert "dup-test-1" in accepted_item_ids

def test_mock_source_ingestion_via_manager():
    # Explicitly clear global state to ensure test isolation
    accepted_items.clear()
    accepted_item_ids.clear()

    # Create a fresh instance of MockSource and IngestionManager for this test
    mock_source = MockSource()
    ingestion_manager = IngestionManager(
        sources=[mock_source],
        interval=30, # Doesn't matter much for this test, but keep consistent
        number_initial_post_per_source=5 # Ensure this matches test expectation
    )
    ingestion_manager.start() # Start the manager within the test scope

    # Simulate initial state by manually adding items that would have been fetched before the continuous phase
    initial_test_mock_items_for_state = [
        NewsItem(
            id="synth-1", source="mock-api", title="Synthetic Event 1: Critical Security Patch Released", body="A major security vulnerability has been discovered and patched in enterprise software.",
            published_at=datetime(2024, 7, 15, 10, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-2", source="mock-api", title="Synthetic Event 2: New AI Chip Achieves Breakthrough Performance", body="Researchers announce a new chip design with unprecedented processing power for AI tasks.",
            published_at=datetime(2024, 7, 15, 11, 30, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-3", source="mock-api", title="Synthetic Event 3: Cloud Provider Outage Impacts Multiple Services", body="A major cloud provider experiences a widespread outage affecting various customer services globally.",
            published_at=datetime(2024, 7, 15, 9, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-4", source="mock-api", title="Synthetic Event 4: Minor Software Update for Legacy System", body="A small patch was released for an older internal system.",
            published_at=datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        ),
    ]

    for item in initial_test_mock_items_for_state:
        accepted_items.append(item)
        accepted_item_ids.add(item.id)

    # Manually set the last fetched timestamp for the mock-api source to simulate that synth-4 was the newest at last fetch
    ingestion_manager.last_fetched_timestamps["mock-api"] = datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Verify initial items are present (these are the ones we just manually added)
    response = client.get("/retrieve")
    assert response.status_code == 200
    retrieved_items_initial = [NewsItem(**item_data) for item_data in response.json()]

    mock_items_initial = [item for item in retrieved_items_initial if item.source == "mock-api"]
    assert len(mock_items_initial) == 4 # Now expecting exactly 4 initially
    assert any(item.id == "synth-1" for item in mock_items_initial)
    assert any(item.id == "synth-2" for item in mock_items_initial)
    assert any(item.id == "synth-3" for item in mock_items_initial)
    assert any(item.id == "synth-4" for item in mock_items_initial)

    # Verify sorting of initial mock items (based on original order in mock_source_data.py)
    mock_items_initial_sorted = sorted(mock_items_initial, key=lambda x: x.published_at, reverse=True)
    assert mock_items_initial_sorted[0].id == "synth-4"
    assert mock_items_initial_sorted[1].id == "synth-2"
    assert mock_items_initial_sorted[2].id == "synth-1"
    assert mock_items_initial_sorted[3].id == "synth-3"

    # Simulate a continuous fetch cycle - with new items available
    # This should now fetch synth-5 and synth-6
    print(f"Before continuous fetch - last_fetched_timestamps: {ingestion_manager.last_fetched_timestamps}")

    # Run continuous fetch
    new_mock_items_from_continuous_fetch = ingestion_manager.continuous_fetch_sources()

    print(f"After continuous fetch - new_mock_items_from_continuous_fetch: {[item.published_at for item in new_mock_items_from_continuous_fetch]}")

    # Manually add to accepted_items to simulate main.py's continuous ingestion logic
    newly_added_count_continuous = 0
    for item in new_mock_items_from_continuous_fetch:
        if item.id not in accepted_item_ids:
            accepted_items.append(item)
            accepted_item_ids.add(item.id)
            newly_added_count_continuous += 1
    
    assert newly_added_count_continuous == 2 # Expect synth-5 and synth-6 to be added
    assert len(accepted_items) == (len(mock_items_initial) + 2) # Total items increased by 2
    
    # Verify that the new items are present in the overall accepted_items
    response = client.get("/retrieve")
    assert response.status_code == 200
    retrieved_items_after_continuous = [NewsItem(**item_data) for item_data in response.json()]
    
    assert any(item.id == "synth-5" for item in retrieved_items_after_continuous)
    assert any(item.id == "synth-6" for item in retrieved_items_after_continuous)

    # Verify overall sorting (newest items should be at the top)
    # The actual order of all items, including the new ones
    assert retrieved_items_after_continuous[0].id == "synth-6" # Newest
    assert retrieved_items_after_continuous[1].id == "synth-5" # Second newest
    assert retrieved_items_after_continuous[2].id == "synth-4" # Next
    # And so on...
    ingestion_manager.stop() # Stop the manager at the end of the test

def test_retrieve_updates_with_new_items():
    # Explicitly clear global state to ensure test isolation
    accepted_items.clear()
    accepted_item_ids.clear()

    # Create a fresh instance of MockSource and IngestionManager for this test
    mock_source = MockSource()
    ingestion_manager = IngestionManager(
        sources=[mock_source],
        interval=30, # Doesn't matter much for this test
        number_initial_post_per_source=5
    )
    ingestion_manager.start()

    # Simulate initial state: manually add synth-1 to synth-4
    initial_test_mock_items_for_state = [
        NewsItem(
            id="synth-1", source="mock-api", title="Synthetic Event 1: Critical Security Patch Released", body="A major security vulnerability has been discovered and patched in enterprise software.",
            published_at=datetime(2024, 7, 15, 10, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-2", source="mock-api", title="Synthetic Event 2: New AI Chip Achieves Breakthrough Performance", body="Researchers announce a new chip design with unprecedented processing power for AI tasks.",
            published_at=datetime(2024, 7, 15, 11, 30, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-3", source="mock-api", title="Synthetic Event 3: Cloud Provider Outage Impacts Multiple Services", body="A major cloud provider experiences a widespread outage affecting various customer services globally.",
            published_at=datetime(2024, 7, 15, 9, 0, 0, tzinfo=timezone.utc)
        ),
        NewsItem(
            id="synth-4", source="mock-api", title="Synthetic Event 4: Minor Software Update for Legacy System", body="A small patch was released for an older internal system.",
            published_at=datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        ),
    ]

    for item in initial_test_mock_items_for_state:
        accepted_items.append(item)
        accepted_item_ids.add(item.id)

    # Set last fetched timestamp to simulate state after these initial items were fetched
    ingestion_manager.last_fetched_timestamps["mock-api"] = datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Call /retrieve and check the most recent post
    response_before_new = client.get("/retrieve")
    assert response_before_new.status_code == 200
    retrieved_before_new = [NewsItem(**item_data) for item_data in response_before_new.json()]
    assert len(retrieved_before_new) == 4
    assert retrieved_before_new[0].id == "synth-4" # Most recent initially

    # Simulate continuous ingestion: Fetch new items and add them
    new_mock_items_from_continuous_fetch = ingestion_manager.continuous_fetch_sources()
    
    newly_added_count_continuous = 0
    for item in new_mock_items_from_continuous_fetch:
        if item.id not in accepted_item_ids:
            accepted_items.append(item)
            accepted_item_ids.add(item.id)
            newly_added_count_continuous += 1
    
    assert newly_added_count_continuous == 2 # Expect synth-5 and synth-6 to be added

    # 2. Call /retrieve again and check that it has the new ones
    response_after_new = client.get("/retrieve")
    assert response_after_new.status_code == 200
    retrieved_after_new = [NewsItem(**item_data) for item_data in response_after_new.json()]

    assert len(retrieved_after_new) == 6 # Total items should be 4 + 2 new
    assert retrieved_after_new[0].id == "synth-6" # Newest after continuous fetch
    assert retrieved_after_new[1].id == "synth-5" # Second newest
    assert retrieved_after_new[2].id == "synth-4" # Original newest
    
    ingestion_manager.stop()