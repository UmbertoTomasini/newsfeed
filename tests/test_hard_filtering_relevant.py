import json
import os
import pytest
from collections import Counter
from newsfeed.ingestion.filtering import zero_shot_it_relevance_filter
from newsfeed.models import NewsItem

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RED = '\033[91m'
RESET = '\033[0m'

# Load the test cases from the JSON file
with open(os.path.join(os.path.dirname(__file__), "test_cases_relevant.json")) as f:
    test_cases = json.load(f)

@pytest.mark.parametrize("min_score", [0.08])
def test_zero_shot_relevance_filter(min_score):
    y_true = [item["relevant"] for item in test_cases]
    y_pred = [zero_shot_it_relevance_filter(NewsItem(**item), min_score=min_score)[0] == 1 for item in test_cases]

    # Confusion matrix
    cm = Counter((yt, yp) for yt, yp in zip(y_true, y_pred))
    tp = cm[(True, True)]
    tn = cm[(False, False)]
    fp = cm[(False, True)]
    fn = cm[(True, False)]

    # Precision, recall
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    # Collect false positives/negatives
    false_positives = [item for item, t, p in zip(test_cases, y_true, y_pred) if not t and p]
    false_negatives = [item for item, t, p in zip(test_cases, y_true, y_pred) if t and not p]
    fp_list = [f"{item['id']} - {item['title']}" for item in false_positives]
    fn_list = [f"{item['id']} - {item['title']}" for item in false_negatives]

    print(f"{GREEN}\n{'='*40}\nZero-shot filter (min_score={min_score}){RESET}")
    print(f"{YELLOW}Confusion Matrix: TP={tp}, TN={tn}, FP={fp}, FN={fn}{RESET}")
    print(f"{BLUE}Precision: {precision:.2%}{RESET}")
    print(f"{BLUE}Recall: {recall:.2%}{RESET}")
    print(f"{RED}False Positives ({len(false_positives)}): {fp_list}{RESET}")
    print(f"{RED}False Negatives ({len(false_negatives)}): {fn_list}{RESET}")
    print(f"{GREEN}{'='*40}{RESET}")

# To run ablation studies:
# pytest -s newsfeed/tests/test_filtering_relevant.py -k 'filter_set_name and threshold'
# Example: pytest -s newsfeed/tests/test_filtering_relevant.py -k 'sentiment and 0.5'

def test_metrics():
    y_true = [item["relevant"] for item in test_cases]
    y_pred = [zero_shot_it_relevance_filter(NewsItem(**item), min_score=0.08)[0] == 1 for item in test_cases]

    # Confusion matrix
    cm = Counter((yt, yp) for yt, yp in zip(y_true, y_pred))
    tp = cm[(True, True)]
    tn = cm[(False, False)]
    fp = cm[(False, True)]
    fn = cm[(True, False)]

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    print(f"\n[Default threshold 0.08] Confusion Matrix: TP={tp}, TN={tn}, FP={fp}, FN={fn}")
    print(f"Precision: {precision:.2%}")
    print(f"Recall: {recall:.2%}")

    # Optionally, assert minimum performance
    # assert precision > 0.7
    # assert recall > 0.7