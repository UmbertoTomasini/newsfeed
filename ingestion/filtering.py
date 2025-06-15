import logging
import re
import time
import warnings

import torch
from sklearn.metrics import confusion_matrix, precision_score, recall_score
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    pipeline,
)
from transformers.utils import logging as hf_logging

from newsfeed.config import MIN_SCORE
from newsfeed.log_utils import log_accepted, log_info, log_refused

warnings.filterwarnings("ignore", category=UserWarning)
hf_logging.set_verbosity_error()

logger = logging.getLogger(__name__)

# Structured log storage for filter decisions and metrics
FILTER_LOGS = []

# Robust lazy loading for zero-shot classifier with thread safety and logging
_zero_shot_classifier = None
_classifier_loading = False


def get_zero_shot_classifier():
    global _zero_shot_classifier, _classifier_loading

    if _classifier_loading:
        while _classifier_loading:
            time.sleep(0.1)
        return _zero_shot_classifier

    if _zero_shot_classifier is None:
        _classifier_loading = True
        log_info(
            "Initializing zero-shot classifier (first-time load, this may take 10-30 seconds)...",
            source="Filtering",
        )
        try:
            start_time = time.time()
            zero_shot_device = 0 if torch.cuda.is_available() else -1
            _zero_shot_classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                hypothesis_template="This news is about {}.",
                device=zero_shot_device,
            )
            log_info(
                f"Zero-shot classifier loaded successfully in {time.time() - start_time:.1f} seconds",
                source="Filtering",
            )
        except Exception as e:
            logger.error(f"Failed to load zero-shot classifier: {e}")
            _zero_shot_classifier = None
        finally:
            _classifier_loading = False

    return _zero_shot_classifier


# Helper to append suffix to relevant labels
RELEVANT_LABEL_SUFFIX = " (critical and urgent for a IT manager of a company)"
RELEVANT_LABELS = [
    "Outage",
    "Security Incident",
    "Vulnerability",
    "Major Bug",
    "Performance Degradation",
    "Data Loss",
    "Deprecation/EOL",
    "Malfunction/Issue",
    "Database Bug",
    "System/Servers Down",
    "Data corruption",
    "Latency Spikes",
    "Job Failure",
]

NOT_RELEVANT_LABELS = set(
    [
        "Not a critical/urgent issue for a IT manager of a company",
    ]
)

ZERO_SHOT_LABELS = [label + RELEVANT_LABEL_SUFFIX for label in RELEVANT_LABELS] + list(
    NOT_RELEVANT_LABELS
)


# Helper to check if a label is relevant (has the suffix and is not in NOT_RELEVANT_LABELS)
def is_relevant_label(label):
    return label.endswith(RELEVANT_LABEL_SUFFIX)


def get_first_n_sentences(text, n=2):
    if not text:
        return ""
    # Simple sentence splitter: split on period, exclamation, or question mark followed by space or end of string
    sentences = re.split(r"(?<=[.!?]) +", text)
    return " ".join(sentences[:n])


def zero_shot_it_relevance_filter(
    news_item, min_score=MIN_SCORE, fallback_to_body=True
):
    zero_shot_classifier = get_zero_shot_classifier()
    if not zero_shot_classifier:
        log_info = f"[PASS] {news_item.id}: Zero-shot classifier unavailable, passing by default."
        FILTER_LOGS.append(
            {
                "filter": "zero_shot",
                "id": news_item.id,
                "decision": "pass",
                "log": log_info,
            }
        )
        log_accepted(news_item, step="zero_shot_it_relevance_filter")
        return 1, 1.0, None, log_info

    context = ""
    body_snippet = get_first_n_sentences(news_item.body, n=2)
    text_title = context + (news_item.title or "")
    if body_snippet:
        text_title += " " + body_snippet

    result_title = zero_shot_classifier(
        text_title, candidate_labels=ZERO_SHOT_LABELS, multi_label=True
    )

    relevant_scores_title = [
        (label, score)
        for label, score in zip(result_title["labels"], result_title["scores"])
        if is_relevant_label(label)
    ]

    max_score = max([score for _, score in relevant_scores_title], default=0.0)
    is_relevant = any(score >= min_score for _, score in relevant_scores_title)
    binary_label = 1 if is_relevant else 0
    top_relevant_title = (
        max(relevant_scores_title, key=lambda x: x[1])
        if relevant_scores_title
        else (None, 0.0)
    )
    top_label = top_relevant_title[0]
    news_item.top_relevant_label = top_label

    log_info_title = (
        f"{'[PASS]' if is_relevant else '[FILTERED]'} {news_item.id} | {news_item.title}: "
        f"Zero-shot TITLE+BODY2 relevant label '{top_label}' (score={top_relevant_title[1]:.2f})"
    )

    FILTER_LOGS.append(
        {
            "filter": "zero_shot",
            "id": news_item.id,
            "stage": "title+body2",
            "decision": "pass" if is_relevant else "filtered",
            "log": log_info_title,
            "top_relevant_label": top_label,
            "top_relevant_score": top_relevant_title[1],
            "all_scores": list(zip(result_title["labels"], result_title["scores"])),
        }
    )

    # Use the centralized logging functions
    if is_relevant:
        log_accepted(news_item, step="zero_shot_it_relevance_filter")
    else:
        # Store the score and label info on the item so log_refused can use it
        news_item.relevance_score = max_score
        news_item.top_relevant_label = top_label
        log_refused(news_item, step="zero_shot_it_relevance_filter")

    return binary_label, max_score, top_label, log_info_title


def log_filtering_summary(stage_name, items_with_logs, threshold):
    passed = [item for item, (score, logs) in items_with_logs if score > threshold]
    filtered = [item for item, (score, logs) in items_with_logs if score <= threshold]
    logger.info(
        f"[SUMMARY] {stage_name}: {len(passed)} passed, {len(filtered)} filtered out."
    )
    FILTER_LOGS.append(
        {"stage": stage_name, "passed": len(passed), "filtered": len(filtered)}
    )
    for item in filtered:
        log_refused(item)
    return passed, filtered


def assess_with_bigger_model(news_items):
    """
    Assess the relevance of news items using a larger instruction-tuned language model via transformers.
    Returns a dict mapping news_item.id to the model's label ('RELEVANT' or 'NOT_RELEVANT').
    """
    results = {}
    if not news_items:
        return results
    # Load model and tokenizer once
    model_name = "tiiuae/falcon-7b-instruct"  # Instruction-tuned LLM
    try:
        quantization_config = BitsAndBytesConfig(load_in_4bit=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, quantization_config=quantization_config, device_map="auto"
        )
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        generator = pipeline("text-generation", model=model, tokenizer=tokenizer)
    except Exception as e:
        logger.error(f"Failed to load the larger model: {e}")
        for item in news_items:
            results[item.id] = "NOT_RELEVANT"
        return results
    prompt_template = (
        "You are an enterprise IT risk analyst.\n\n"
        "TASK\n------\n"
        "Read the article delimited by <article></article>.\n"
        "Return exactly one word from this list—nothing else:\n\n"
        "RELEVANT     (major cloud outage, CVSS ≥ 7 vuln, 0-day exploit, ransomware in the wild)\n"
        "NOT_RELEVANT (consumer tech, general business news, HR moves, marketing releases)\n\n"
        "EXAMPLES\n--------\n"
        "<article>\nTitle: Major AWS Outage Disrupts Global Services\nBody: Amazon Web Services suffered a major outage today, impacting thousands of businesses worldwide. Critical infrastructure and cloud-hosted applications were unavailable for several hours.\n</article>\nLabel: RELEVANT\n\n"
        "<article>\nTitle: Apple Releases New iPhone 16\nBody: Apple has announced the launch of its latest smartphone, the iPhone 16, featuring a new camera and improved battery life.\n</article>\nLabel: NOT_RELEVANT\n\n"
        "<article>\nTitle: Minor Bug Found in Internal HR Portal\nBody: A small bug was discovered in the company HR portal, causing a minor display issue for some users. The bug does not affect payroll or sensitive data.\n</article>\nLabel: NOT_RELEVANT\n\n"
        "Now, classify the following article:\n\n"
        "<article>\n{article}\n</article>\nLabel:"
    )
    for item in news_items:
        article_text = item.title or ""
        if item.body:
            article_text += " " + item.body[:300]
        else:
            article_text = article_text[:300]
        prompt = prompt_template.format(article=article_text)
        try:
            output = generator(prompt, max_new_tokens=10, do_sample=False)[0][
                "generated_text"
            ]
            # Parse only the relevant part of the output
            relevant_output = output
            if "Now, classify the following article" in relevant_output:
                relevant_output = relevant_output.split(
                    "Now, classify the following article", 1
                )[-1]
            if "Label:" in relevant_output:
                relevant_output = relevant_output.split("Label:", 1)[-1]
            # Extract the label from the relevant part (look for RELEVANT or NOT_RELEVANT)
            label = None
            output_upper = relevant_output.upper()
            if re.search(r"\bNOT_RELEVANT\b", output_upper):
                label = "NOT_RELEVANT"
            elif re.search(r"\bRELEVANT\b", output_upper):
                label = "RELEVANT"
            else:
                logger.warning(
                    f"Unexpected label from the larger model: {output} for item {item.id}"
                )
                label = "NOT_RELEVANT"

            results[item.id] = label

        except Exception as e:
            logger.error(f"Larger model inference failed for item {item.id}: {e}")
            results[item.id] = "NOT_RELEVANT"
    return results


def evaluate_pipeline_vs_model(pipeline_labels, model_labels):
    """
    Compare pipeline labels to model labels (ground truth) and compute precision, recall, and confusion matrix.
    pipeline_labels: dict of id -> 'RELEVANT' or 'NOT_RELEVANT'
    model_labels: dict of id -> 'RELEVANT' or 'NOT_RELEVANT'
    Returns: (precision, recall, confusion_matrix)
    """
    y_true = []
    y_pred = []
    for id in model_labels:
        if id in pipeline_labels:
            y_true.append(1 if model_labels[id] == "RELEVANT" else 0)
            y_pred.append(1 if pipeline_labels[id] == "RELEVANT" else 0)
    if not y_true:
        return 0.0, 0.0, None
    precision = precision_score(y_true, y_pred)
    recall = recall_score(y_true, y_pred)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])

    return precision, recall, cm
