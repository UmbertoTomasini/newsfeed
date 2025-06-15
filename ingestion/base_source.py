from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional


class BaseSource(ABC):
    @abstractmethod
    def fetch_news(
        self,
        posts_limit: Optional[int] = None,
        since_timestamp: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Fetch news items from the source.
        Returns a list of dictionaries, each representing a news item.
        posts_limit: If provided, fetch up to this many most recent posts.
        since_timestamp: If provided, fetch posts published after this timestamp.
        """
        pass
