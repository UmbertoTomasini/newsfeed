import logging
import os
import time
from datetime import datetime
from typing import List, Set

from fastapi import FastAPI

import newsfeed.log_utils as log_utils
from newsfeed.background_tasks import BackgroundTaskManager
from newsfeed.config import (
    ASSESS_CORRECTNESS_WITH_BIGGER_MODEL,
    ASSESS_EFFICIENCY,
    INTERVAL,
    NUMBER_INITIAL_POST_PER_SOURCE,
)
from newsfeed.ingestion.ars_technica_source import ArsTechnicaSource
from newsfeed.ingestion.manager import IngestionManager
from newsfeed.ingestion.mock_source_data import MockSource
from newsfeed.ingestion.reddit_source import RedditSource
from newsfeed.log_utils import (
    log_accepted,
    log_efficiency,
    log_info,
    log_resource_usage,
    setup_run_logger,
)
from newsfeed.models import NewsItem

# ----------------------------------------------------------------------
# End of import block
# ----------------------------------------------------------------------
_startup_time = time.perf_counter()  # start the timer ASAP
# ----------------------------------------------------------------------
# Imports – keep them contiguous so Ruff/Black are happy
# ----------------------------------------------------------------------


def log_startup_time(msg: str) -> None:
    print(f"[STARTUP {time.perf_counter() - _startup_time:6.2f}s] {msg}")


# Log milestones you care about *after* the imports
log_startup_time("Imports complete – starting initialization")


# Ensure logs subdirectories exist
log_base_dir = os.path.join(os.path.dirname(__file__), "logs")
efficiency_log_dir = os.path.join(log_base_dir, "efficiency")
items_log_dir = os.path.join(log_base_dir, "items")
run_log_dir = os.path.join(log_base_dir, "run")
os.makedirs(efficiency_log_dir, exist_ok=True)
os.makedirs(items_log_dir, exist_ok=True)
os.makedirs(run_log_dir, exist_ok=True)

# Add timestamp to log file names
log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
efficiency_log_file_path = os.path.join(
    efficiency_log_dir, f"newsfeed_efficiency_{log_time}.log"
)
items_log_file_path = os.path.join(items_log_dir, f"newsfeed_items_{log_time}.log")

# Configure efficiency logging (only efficiency metrics)
efficiency_logger = logging.getLogger("efficiency_logger")
efficiency_logger.setLevel(logging.INFO)
efficiency_handler = logging.FileHandler(efficiency_log_file_path)
efficiency_handler.setLevel(logging.INFO)
efficiency_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
efficiency_handler.setFormatter(efficiency_formatter)
efficiency_logger.addHandler(efficiency_handler)
efficiency_logger.propagate = False

# Configure items logging (accepted/refused only)
items_logger = logging.getLogger("items_logger")
items_logger.setLevel(logging.INFO)
items_handler = logging.FileHandler(items_log_file_path)
items_handler.setLevel(logging.INFO)
items_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
items_handler.setFormatter(items_formatter)
items_logger.addHandler(items_handler)
items_logger.propagate = False

# Set up the run logger
run_logger = setup_run_logger()


log_utils.items_logger = items_logger
log_utils.efficiency_logger = efficiency_logger
log_utils.run_logger = run_logger

# Log startup
log_info("FastAPI application starting up", source="MAIN")

app = FastAPI()

app.json_encoders = {datetime: lambda dt: dt.isoformat()}

# In-memory store for accepted news items and their IDs for fast deduplication
accepted_items: List[NewsItem] = []
accepted_item_ids: Set[str] = set()

# In-memory store for all news items (accepted + filtered) for assessment
all_items: List[NewsItem] = []

# Set up the ingestion manager with Reddit, Ars Technica, and Mock sources
reddit_source_sysadmin = RedditSource(subreddit="sysadmin")
reddit_source_outages = RedditSource(subreddit="outages")
reddit_source_cybersecurity = RedditSource(subreddit="cybersecurity")
ars_source = ArsTechnicaSource()
mock_source = MockSource()
ingestion_manager = IngestionManager(
    sources=[
        reddit_source_sysadmin,
        reddit_source_outages,
        reddit_source_cybersecurity,
        ars_source,
    ],
    interval=INTERVAL,  # Use config value
    number_initial_post_per_source=NUMBER_INITIAL_POST_PER_SOURCE,  # Use config value
)

# After setting up the ingestion_manager, create the background task manager
background_task_manager = BackgroundTaskManager(
    ingestion_manager=ingestion_manager,
    accepted_items=accepted_items,
    accepted_item_ids=accepted_item_ids,
    all_items=all_items,
)

# Create the lifespan context
lifespan = background_task_manager.create_lifespan_context()

# Update the FastAPI app initialization
app = FastAPI(lifespan=lifespan)


@app.get("/")
def read_root():
    print("Root endpoint accessed.")
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str = None):
    print(f"Items endpoint accessed with item_id: {item_id}, q: {q}")
    return {"item_id": item_id, "q": q}


@app.post("/ingest")
def ingest_news(items: List[NewsItem]):
    print(f"Ingest endpoint received {len(items)} items.")
    ingest_latency = None
    if ASSESS_EFFICIENCY:
        import time

        ingest_start = time.perf_counter()
    newly_ingested_count = 0
    for item in items:
        if item.id not in accepted_item_ids:
            accepted_items.append(item)
            accepted_item_ids.add(item.id)
            newly_ingested_count += 1
            log_accepted(item, step="ingest_news")

    # Use the background task manager's method
    background_task_manager.update_recency_final_scores()

    if ASSESS_EFFICIENCY:
        ingest_end = time.perf_counter()
        ingest_latency = ingest_end - ingest_start
        throughput = (
            newly_ingested_count / ingest_latency if ingest_latency > 0 else 0.0
        )

        # Log metrics on separate lines
        log_efficiency(f"Latency: {ingest_latency:.4f} seconds", step="/ingest")
        log_efficiency(f"Throughput: {throughput:.2f} items/s", step="/ingest")
        log_efficiency(
            f"Items processed: {newly_ingested_count} new items", step="/ingest"
        )
        log_resource_usage("/ingest")

    print(
        f"Ingest endpoint processed. Added {newly_ingested_count} new items. Total accumulated items: {len(accepted_items)}."
    )
    return {"status": "ACK"}


@app.get("/retrieve", response_model=List[NewsItem])
def retrieve_news():
    print(f"Retrieve endpoint accessed. Returning {len(accepted_items)} items.")
    retrieve_latency = None
    if ASSESS_EFFICIENCY:
        import time

        retrieve_start = time.perf_counter()

    # Use the background task manager's method
    background_task_manager.update_recency_final_scores()

    if ASSESS_EFFICIENCY:
        retrieve_end = time.perf_counter()
        retrieve_latency = retrieve_end - retrieve_start
        throughput = (
            len(accepted_items) / retrieve_latency if retrieve_latency > 0 else 0.0
        )

        # Log metrics on separate lines
        log_efficiency(f"Latency: {retrieve_latency:.4f} seconds", step="/retrieve")
        log_efficiency(f"Throughput: {throughput:.2f} items/s", step="/retrieve")
        log_efficiency(f"Items returned: {len(accepted_items)} items", step="/retrieve")
        log_resource_usage("/retrieve")

    # Return all accepted items, sorted by final_score (descending), fallback to published_at
    return sorted(
        accepted_items,
        key=lambda x: (
            x.final_score if x.final_score is not None else 0,
            x.published_at,
        ),
        reverse=True,
    )


@app.get("/retrieve-all")
def retrieve_all_news():
    if not ASSESS_CORRECTNESS_WITH_BIGGER_MODEL:
        return {"error": "Assessment mode is not enabled."}
    print(f"/retrieve-all called. all_items has {len(all_items)} items.")
    if all_items:
        print(f"Sample IDs: {[item.id for item in all_items[:5]]}")
    else:
        print("all_items is empty.")
    if ASSESS_EFFICIENCY:
        import time

        retrieve_all_start = time.perf_counter()
    # Sort by final_score (None treated as 0), descending
    sorted_items = sorted(
        all_items,
        key=lambda item: item.final_score if item.final_score is not None else 0,
        reverse=True,
    )
    if ASSESS_EFFICIENCY:
        retrieve_all_end = time.perf_counter()
        retrieve_all_latency = retrieve_all_end - retrieve_all_start
        throughput = (
            len(sorted_items) / retrieve_all_latency
            if retrieve_all_latency > 0
            else 0.0
        )

        # Log metrics on separate lines
        log_efficiency(
            f"Latency: {retrieve_all_latency:.4f} seconds", step="/retrieve-all"
        )
        log_efficiency(f"Throughput: {throughput:.2f} items/s", step="/retrieve-all")
        log_efficiency(
            f"Items returned: {len(sorted_items)} items", step="/retrieve-all"
        )
        log_resource_usage("/retrieve-all")
    return sorted_items
