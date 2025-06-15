import logging
from datetime import datetime, timezone
from typing import List, Optional

import requests

from newsfeed.models import NewsItem

from .base_source import BaseSource

logger = logging.getLogger(__name__)


class RedditSource(BaseSource):
    def __init__(self, subreddit: str, source_name: str = None):
        self.subreddit = subreddit
        self.source_name = source_name or f"reddit/{subreddit}"
        logger.info(f"RedditSource initialized for subreddit: {self.subreddit}")

    def fetch_news(
        self,
        posts_limit: Optional[int] = None,
        since_timestamp: Optional[datetime] = None,
    ) -> List[NewsItem]:
        items = []
        try:
            if since_timestamp:
                # For continuous fetch: Reddit API doesn't directly support 'since' timestamp
                # for /new.json, so we fetch a recent batch (up to 50 posts) and filter client-side.
                url = f"https://www.reddit.com/r/{self.subreddit}/new.json?limit=50"  # Fetch a reasonable batch
                logger.info(
                    f"Fetching new posts from Reddit since {since_timestamp.isoformat()}: {url}"
                )
            elif posts_limit is not None:
                # For initial fetch: get a specific limit
                url = f"https://www.reddit.com/r/{self.subreddit}/new.json?limit={posts_limit}"
                logger.info(f"Fetching initial {posts_limit} posts from Reddit: {url}")
            else:
                # Fallback (shouldn't happen if manager calls correctly)
                url = f"https://www.reddit.com/r/{self.subreddit}/new.json?limit=10"
                logger.warning(
                    f"Neither posts_limit nor since_timestamp provided for RedditSource. Defaulting to 10. URL: {url}"
                )

            headers = {"User-Agent": "newsfeed-bot/0.1"}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            fetched_count = 0
            for post in data.get("data", {}).get("children", []):
                post_data = post["data"]

                post_utc_dt = datetime.fromtimestamp(
                    post_data["created_utc"], tz=timezone.utc
                )

                # If continuous fetch, only include posts strictly newer than since_timestamp
                if since_timestamp and post_utc_dt <= since_timestamp:
                    continue  # Skip this post if it's not newer

                news_item = NewsItem(
                    id=post_data["id"],
                    source=self.source_name,
                    title=post_data.get("title", ""),
                    body=post_data.get("selftext", ""),
                    published_at=post_utc_dt,
                )
                items.append(news_item)
                fetched_count += 1

            logger.info(
                f"Successfully processed {fetched_count} items from {self.source_name} ({len(items)} passing filter)."
            )
            return items

        except requests.exceptions.RequestException as e:
            logger.error(
                f"Error fetching from Reddit source {self.source_name} ({url}): {e}",
                exc_info=True,
            )
            return []
        except Exception as e:
            logger.error(
                f"An unexpected error occurred in Reddit source {self.source_name}: {e}",
                exc_info=True,
            )
            return []
