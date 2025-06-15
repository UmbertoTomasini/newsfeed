# config.py

# Minimum score threshold for the zero-shot relevance filter.
# Items with a relevant label score below this value will be filtered out.
MIN_SCORE = 0.08

# Maximum number of news items to keep in memory (accepted_items).
# When this limit is exceeded, items with the lowest final_score are removed.
MAX_ITEMS = 100

# Interval (in seconds) between each background ingestion (fetch) cycle.
INTERVAL = 30  # seconds

# Number of posts to fetch per source during the initial ingestion.
NUMBER_INITIAL_POST_PER_SOURCE = 5

# Persistence time for recency decay, in seconds.
# For example, 86400 = 1 day.
PERSISTENCE_TIME = 86400

# Boolean to enable correctness assessment with a larger model (e.g., Mixtral 8x7B)
ASSESS_CORRECTNESS_WITH_BIGGER_MODEL = False

# Enable or disable efficiency assessment (latency/throughput measurement)
ASSESS_EFFICIENCY = True 