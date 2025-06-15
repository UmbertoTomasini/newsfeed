import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from .base_source import BaseSource
from newsfeed.models import NewsItem
from newsfeed.ingestion.filtering import zero_shot_it_relevance_filter, log_filtering_summary, ZERO_SHOT_LABELS
import math
from newsfeed.config import INTERVAL, NUMBER_INITIAL_POST_PER_SOURCE, MIN_SCORE, PERSISTENCE_TIME
from newsfeed.log_utils import log_info, log_error, log_accepted, log_refused

logger = logging.getLogger(__name__)

def compute_recency_weight(published_time, now=None, lambda_=None):
    if now is None:
        now = datetime.now(timezone.utc)
    if lambda_ is None:
        # Compute lambda_ from config
        persistence_time = PERSISTENCE_TIME
        lambda_ = 1 / persistence_time if persistence_time > 0 else 0.0
    delta_hours = (now - published_time).total_seconds() / 3600
    return math.exp(-lambda_ * delta_hours)

class IngestionManager:
    def __init__(self, sources: List[BaseSource], interval: int = INTERVAL, number_initial_post_per_source: int = NUMBER_INITIAL_POST_PER_SOURCE):
        self.sources = sources
        self.interval = interval  # seconds for continuous fetch
        self.number_initial_post_per_source = number_initial_post_per_source
        self.last_fetched_timestamps: Dict[str, datetime] = {}
        self._timer = None
        self._running = False
        log_info(f"IngestionManager initialized with {len(sources)} sources, interval={interval}s, initial_limit={number_initial_post_per_source}.", source="IngestionManager")

    def start(self):
        self._running = True
        log_info("IngestionManager started. Ready for initial fetch and continuous polling.", source="IngestionManager")

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()
        log_info("IngestionManager stopped.", source="IngestionManager")

    def initial_fetch_sources(self, store_filtered: bool = False) -> List[NewsItem] | Tuple[List[NewsItem], List[NewsItem]]:
        """
        Performs the initial fetch for all sources, getting the most recent 'number_initial_post_per_source' items.
        Updates last_fetched_timestamps for each source based on the initial fetch.
        """
        log_info("Manager performing initial ingestion fetch.", source="IngestionManager")
        all_new_items: List[NewsItem] = []
        all_filtered_items: List[NewsItem] = []
        
        for source in self.sources:
            source_name = getattr(source, 'source_name', str(source))
            try:
                log_info(f"Performing initial fetch from source: {source_name} (limit={self.number_initial_post_per_source})", source="IngestionManager")
                fetched_items = source.fetch_news(posts_limit=self.number_initial_post_per_source)
                
                if fetched_items:
                    sorted_items = sorted(fetched_items, key=lambda x: x.published_at, reverse=True)
                    newest_timestamp = sorted_items[0].published_at
                    self.last_fetched_timestamps[source_name] = newest_timestamp
                    log_info(f"Initially fetched {len(fetched_items)} items from {source_name}. Newest timestamp: {newest_timestamp}", source="IngestionManager")
                    
                    now = datetime.now(timezone.utc)
                    for item in fetched_items:
                        binary_label, max_score, top_label, log_info_filter = zero_shot_it_relevance_filter(item, min_score=MIN_SCORE)
                        
                        # Store score and label on the item for log_refused to use
                        item.relevance_score = max_score
                        item.top_relevant_label = top_label
                        
                        if binary_label:
                            item.recency_weight = compute_recency_weight(item.published_at, now)
                            item.final_score = item.relevance_score * item.recency_weight if item.relevance_score is not None and item.recency_weight is not None else None
                            all_new_items.append(item)
                            # log_accepted is already called in zero_shot_it_relevance_filter
                        else:
                            all_filtered_items.append(item)
                            # log_refused is already called in zero_shot_it_relevance_filter
                else:
                    log_info(f"No items fetched during initial fetch from {source_name}.", source="IngestionManager")
            except Exception as e:
                log_error(f"Error during initial fetch from source {source_name}: {e}", source="IngestionManager", exc_info=True)
        
        log_info(f"Manager initial ingestion fetch completed. Total items: {len(all_new_items)} accepted, {len(all_filtered_items)} filtered.", source="IngestionManager")
        
        if store_filtered:
            return all_new_items, all_filtered_items
        return all_new_items

    def continuous_fetch_sources(self, store_filtered: bool = False) -> List[NewsItem] | Tuple[List[NewsItem], List[NewsItem]]:
        """
        Performs continuous fetch for all sources, getting items newer than the last fetched timestamp.
        Updates last_fetched_timestamps for each source.
        """
        log_info("Manager performing continuous ingestion fetch.", source="IngestionManager")
        all_new_items: List[NewsItem] = []
        all_filtered_items: List[NewsItem] = []
        
        for source in self.sources:
            source_name = getattr(source, 'source_name', str(source))
            since_timestamp = self.last_fetched_timestamps.get(source_name)
            try:
                log_info(f"Performing continuous fetch from source: {source_name} (since: {since_timestamp or 'beginning'})", source="IngestionManager")
                fetched_items = source.fetch_news(since_timestamp=since_timestamp)
                
                if fetched_items:
                    truly_new_items = [
                        item for item in fetched_items 
                        if since_timestamp is None or item.published_at > since_timestamp
                    ]
                    
                    if truly_new_items:
                        sorted_new_items = sorted(truly_new_items, key=lambda x: x.published_at, reverse=True)
                        newest_timestamp = sorted_new_items[0].published_at
                        self.last_fetched_timestamps[source_name] = newest_timestamp
                        now = datetime.now(timezone.utc)
                        
                        for item in truly_new_items:
                            binary_label, max_score, top_label, log_info_filter = zero_shot_it_relevance_filter(item, min_score=MIN_SCORE)
                            
                            # Store score and label on the item for log_refused to use
                            item.relevance_score = max_score
                            item.top_relevant_label = top_label
                            
                            if binary_label:
                                item.recency_weight = compute_recency_weight(item.published_at, now)
                                item.final_score = item.relevance_score * item.recency_weight if item.relevance_score is not None and item.recency_weight is not None else None
                                all_new_items.append(item)
                                # log_accepted is already called in zero_shot_it_relevance_filter
                            else:
                                all_filtered_items.append(item)
                                # log_refused is already called in zero_shot_it_relevance_filter
                        
                        log_info(f"Continuously fetched {len(truly_new_items)} new items from {source_name}. Newest timestamp: {newest_timestamp}", source="IngestionManager")
                    else:
                        log_info(f"No new items found from {source_name} during continuous fetch.", source="IngestionManager")
                else:
                    log_info(f"No items returned from {source_name} during continuous fetch.", source="IngestionManager")
            except Exception as e:
                log_error(f"Error during continuous fetch from source {source_name}: {e}", source="IngestionManager", exc_info=True)
        
        log_info(f"Manager continuous ingestion fetch completed. Total new items: {len(all_new_items)} accepted, {len(all_filtered_items)} filtered.", source="IngestionManager")
        
        if store_filtered:
            return all_new_items, all_filtered_items
        return all_new_items