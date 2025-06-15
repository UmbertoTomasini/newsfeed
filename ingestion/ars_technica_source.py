import logging
from datetime import datetime, timezone
from typing import List, Optional

import feedparser

from newsfeed.models import NewsItem

from .base_source import BaseSource

logger = logging.getLogger(__name__)


class ArsTechnicaSource(BaseSource):
    def __init__(self, source_name: str = "ars-technica"):
        self.source_name = source_name
        self.feed_url = "http://feeds.arstechnica.com/arstechnica/index"
        logger.info(f"ArsTechnicaSource initialized for feed: {self.feed_url}")

    def fetch_news(
        self,
        posts_limit: Optional[int] = None,
        since_timestamp: Optional[datetime] = None,
    ) -> List[NewsItem]:
        items = []
        try:
            logger.info(f"Fetching from Ars Technica: {self.feed_url}")
            feed = feedparser.parse(self.feed_url)

            if feed.bozo:
                logger.warning(
                    f"Feedparser encountered errors for {self.source_name}: {feed.bozo_exception}"
                )

            fetched_count = 0
            for entry in feed.entries:  # Iterate all entries to find recent ones
                # Convert time.struct_time to timezone-aware UTC datetime
                published_time_struct = entry.published_parsed
                utc_dt = datetime(
                    published_time_struct.tm_year,
                    published_time_struct.tm_mon,
                    published_time_struct.tm_mday,
                    published_time_struct.tm_hour,
                    published_time_struct.tm_min,
                    published_time_struct.tm_sec,
                    tzinfo=timezone.utc,
                )

                # Apply filtering based on since_timestamp for continuous fetch
                if since_timestamp and utc_dt <= since_timestamp:
                    continue  # Skip this post if it's not strictly newer

                news_item = NewsItem(
                    id=entry.get("id", entry.get("link")),
                    source=self.source_name,
                    title=entry.get("title", ""),
                    body=entry.get("summary", ""),
                    published_at=utc_dt,
                )
                items.append(news_item)
                fetched_count += 1

                # Apply posts_limit only for initial fetch (when since_timestamp is None)
                if (
                    posts_limit is not None
                    and len(items) >= posts_limit
                    and not since_timestamp
                ):
                    break  # Stop if we've collected enough for initial limit

            logger.info(
                f"Successfully processed {fetched_count} items from {self.source_name} ({len(items)} passing filter/limit)."
            )
            return items

        except Exception as e:
            logger.error(
                f"Error fetching from Ars Technica source {self.source_name} ({self.feed_url}): {e}",
                exc_info=True,
            )
            return []
