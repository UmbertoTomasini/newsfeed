import asyncio
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Set

from fastapi import FastAPI

from newsfeed.config import (
    ASSESS_CORRECTNESS_WITH_BIGGER_MODEL,
    ASSESS_EFFICIENCY,
    MAX_ITEMS,
    PERSISTENCE_TIME,
)
from newsfeed.log_utils import log_accepted, log_efficiency, log_resource_usage
from newsfeed.models import NewsItem


class BackgroundTaskManager:
    """Manages background ingestion tasks for the news feed application"""

    def __init__(
        self,
        ingestion_manager,
        accepted_items: List[NewsItem],
        accepted_item_ids: Set[str],
        all_items: List[NewsItem] = None,
    ):
        self.ingestion_manager = ingestion_manager
        self.accepted_items = accepted_items
        self.accepted_item_ids = accepted_item_ids
        self.all_items = all_items if all_items is not None else []
        self.shutdown_flag = False

    def update_recency_final_scores(self):
        """Update recency weights and final scores for all accepted items"""
        if not self.accepted_items:
            return

        reference_time = datetime.now(timezone.utc)
        persistence_time = PERSISTENCE_TIME * self.ingestion_manager.interval
        recency_lambda = 1 / persistence_time if persistence_time > 0 else 0.0

        for item in self.accepted_items:
            if item.relevance_score is not None:
                delta_seconds = (reference_time - item.published_at).total_seconds()
                item.recency_weight = math.exp(-recency_lambda * delta_seconds)
                item.final_score = item.relevance_score * item.recency_weight
            else:
                item.recency_weight = None
                item.final_score = None

        # Trim accepted_items to MAX_ITEMS by final_score
        if len(self.accepted_items) > MAX_ITEMS:
            self.accepted_items.sort(
                key=lambda x: (x.final_score if x.final_score is not None else -1),
                reverse=True,
            )
            del self.accepted_items[MAX_ITEMS:]
            # Update the set of IDs
            self.accepted_item_ids.clear()
            self.accepted_item_ids.update(item.id for item in self.accepted_items)

    async def background_ingest_async(self):
        """Async version of background ingestion"""
        while not self.shutdown_flag:
            print("Starting continuous background ingestion cycle.")
            ingestion_latency = None

            if ASSESS_EFFICIENCY:
                import time

                ingestion_start = time.perf_counter()

            # Run the blocking I/O in a thread pool
            loop = asyncio.get_event_loop()

            if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL:
                result = await loop.run_in_executor(
                    None,
                    lambda: self.ingestion_manager.continuous_fetch_sources(
                        store_filtered=True
                    ),
                )
                new_items_from_sources, filtered_items_from_sources = result
                self.all_items.extend(new_items_from_sources)
                self.all_items.extend(filtered_items_from_sources)
            else:
                new_items_from_sources = await loop.run_in_executor(
                    None, self.ingestion_manager.continuous_fetch_sources
                )
                filtered_items_from_sources = []

            newly_added_count = 0
            for item in new_items_from_sources:
                if item.id not in self.accepted_item_ids:
                    self.accepted_items.append(item)
                    self.accepted_item_ids.add(item.id)
                    newly_added_count += 1
                    log_accepted(item, step="background_ingest")

            self.update_recency_final_scores()

            if ASSESS_EFFICIENCY:
                ingestion_end = time.perf_counter()
                ingestion_latency = ingestion_end - ingestion_start
                throughput = (
                    newly_added_count / ingestion_latency
                    if ingestion_latency > 0
                    else 0.0
                )

                # Log metrics on separate lines
                log_efficiency(
                    f"Latency: {ingestion_latency:.4f} seconds", step="Ingestion"
                )
                log_efficiency(
                    f"Throughput: {throughput:.2f} items/s", step="Ingestion"
                )
                log_efficiency(
                    f"Items processed: {newly_added_count} new items", step="Ingestion"
                )
                log_resource_usage("Ingestion")

            print(
                f"Finished continuous background ingestion cycle. Added {newly_added_count} new items. "
                f"Total accumulated items: {len(self.accepted_items)}."
            )

            # Wait for the interval
            await asyncio.sleep(self.ingestion_manager.interval)

    async def initial_fetch_async(self):
        """Perform initial fetch of news items"""
        startup_latency = None
        if ASSESS_EFFICIENCY:
            import time

            startup_start = time.perf_counter()

        self.ingestion_manager.start()

        # Initial fetch
        loop = asyncio.get_event_loop()
        if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL:
            result = await loop.run_in_executor(
                None,
                lambda: self.ingestion_manager.initial_fetch_sources(
                    store_filtered=True
                ),
            )
            initial_items, filtered_items = result
            self.all_items.extend(initial_items)
            self.all_items.extend(filtered_items)
        else:
            initial_items = await loop.run_in_executor(
                None, self.ingestion_manager.initial_fetch_sources
            )
            filtered_items = []

        initial_added_count = 0
        for item in initial_items:
            if item.id not in self.accepted_item_ids:
                self.accepted_items.append(item)
                self.accepted_item_ids.add(item.id)
                initial_added_count += 1

        self.update_recency_final_scores()

        if ASSESS_EFFICIENCY:
            startup_end = time.perf_counter()
            startup_latency = startup_end - startup_start
            throughput = (
                initial_added_count / startup_latency if startup_latency > 0 else 0.0
            )

            # Log metrics on separate lines
            log_efficiency(f"Latency: {startup_latency:.4f} seconds", step="Startup")
            log_efficiency(f"Throughput: {throughput:.2f} items/s", step="Startup")
            log_efficiency(
                f"Items processed: {initial_added_count} items", step="Startup"
            )
            log_resource_usage("Startup")

        print(
            f"Initial fetch completed. Added {initial_added_count} items. "
            f"Total accumulated items: {len(self.accepted_items)}."
        )

        return initial_added_count

    def create_lifespan_context(self):
        """Create the lifespan context manager for FastAPI"""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            print("Application startup initiated.")

            # Perform initial fetch
            await self.initial_fetch_async()

            # Start background task
            task = asyncio.create_task(self.background_ingest_async())
            print("Application startup complete. Continuous ingestion scheduled.")

            yield

            # Shutdown
            print("Application shutdown initiated.")
            self.shutdown_flag = True
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.ingestion_manager.stop()
            print("Application shutdown complete.")

        return lifespan
