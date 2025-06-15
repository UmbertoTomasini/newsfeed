import logging
from datetime import datetime, timezone
from typing import List, Optional

from newsfeed.models import NewsItem

from .base_source import BaseSource

logger = logging.getLogger(__name__)


class MockSource(BaseSource):
    def __init__(self, source_name: str = "mock-api"):
        self.source_name = source_name
        # Add more synthetic events with later timestamps
        self.all_synthetic_events = sorted(
            [
                NewsItem(
                    id="synth-1",
                    source=self.source_name,
                    title="Critical Outage in Data Center",
                    body="A major outage has impacted the main data center, causing downtime for multiple services.",
                    published_at=datetime(2024, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
                ),
                NewsItem(
                    id="synth-2",
                    source=self.source_name,
                    title="Severe Latency Issue Detected",
                    body="Users are experiencing severe latency spikes across the network.",
                    published_at=datetime(2024, 7, 15, 11, 30, 0, tzinfo=timezone.utc),
                ),
                NewsItem(
                    id="synth-3",
                    source=self.source_name,
                    title="Cloud Provider Outage Impacts Multiple Services",
                    body="A major cloud provider experiences a widespread outage affecting various customer services globally.",
                    published_at=datetime(2024, 7, 15, 9, 0, 0, tzinfo=timezone.utc),
                ),
                NewsItem(
                    id="synth-4",
                    source=self.source_name,
                    title="Database Bug Causes Data Corruption",
                    body="A bug in the database system has led to data corruption in several tables.",
                    published_at=datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
                ),
                # NEW SYNTHETIC EVENTS FOR CONTINUOUS FETCHING TEST
                NewsItem(
                    id="synth-5",
                    source=self.source_name,
                    title="Major Data Breach Discovered",
                    body="Security firm reports a massive data breach affecting millions of users.",
                    published_at=datetime(
                        2024, 7, 15, 13, 0, 0, tzinfo=timezone.utc
                    ),  # Newer than synth-4
                ),
                NewsItem(
                    id="synth-6",
                    source=self.source_name,
                    title="Performance Degradation in Web Services",
                    body="Web services are experiencing performance degradation due to high load.",
                    published_at=datetime(
                        2024, 7, 15, 13, 15, 0, tzinfo=timezone.utc
                    ),  # Newer than synth-5
                ),
            ],
            key=lambda x: x.published_at,
        )  # Sort by published_at ascending for easier filtering
        logger.info(
            f"MockSource initialized with {len(self.all_synthetic_events)} synthetic events."
        )

    def fetch_news(
        self,
        posts_limit: Optional[int] = None,
        since_timestamp: Optional[datetime] = None,
    ) -> List[NewsItem]:
        items_to_return = []
        if since_timestamp:
            logger.info(f"Fetching mock news since {since_timestamp.isoformat()}.")
            # For continuous fetch: return items strictly newer than since_timestamp
            for item in self.all_synthetic_events:
                if item.published_at > since_timestamp:
                    items_to_return.append(item)
        elif posts_limit is not None:
            logger.info(f"Fetching initial {posts_limit} mock news items.")
            # For initial fetch: return the last 'posts_limit' items (most recent)
            items_to_return = self.all_synthetic_events[-posts_limit:]
        else:
            logger.warning(
                "Neither posts_limit nor since_timestamp provided for MockSource. Returning all synthetic events."
            )
            items_to_return = self.all_synthetic_events

        logger.info(
            f"Fetched {len(items_to_return)} items from {self.source_name} (mock data)."
        )
        return items_to_return
