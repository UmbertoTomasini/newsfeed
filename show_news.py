import requests
from rich.console import Console
from rich.table import Table
from rich import box
from datetime import datetime
from newsfeed.config import ASSESS_CORRECTNESS_WITH_BIGGER_MODEL, MIN_SCORE
from newsfeed.ingestion.filtering import assess_with_bigger_model, evaluate_pipeline_vs_model, RELEVANT_LABEL_SUFFIX
from rich.panel import Panel
from rich.text import Text
from rich.table import Table as RichTable
from sklearn.metrics import f1_score
import re
from newsfeed.models import NewsItem
import pdb

API_URL = "http://127.0.0.1:8000/retrieve-all" if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL else "http://127.0.0.1:8000/retrieve"

console = Console()

try:
    response = requests.get(API_URL)
    response.raise_for_status()
    news_items = response.json()
except Exception as e:
    console.print(f"[red]Failed to fetch news from {API_URL}: {e}[/red]")
    exit(1)

if not news_items:
    console.print("[yellow]No news items found.[/yellow]")
    exit(0)

news_items = [NewsItem(**item) for item in news_items]

table = Table(title="Filtered News (Ranked by Relevance x Recency)", box=box.SIMPLE_HEAVY)
table.add_column("Title", style="bold", overflow="fold")
table.add_column("Source", style="cyan")
table.add_column("Published", style="magenta")
table.add_column("Relevance", style="green")
table.add_column("Recency", style="yellow")
table.add_column("Final Score", style="bold blue")
table.add_column("Top Label", style="white")



for item in news_items:
    published = item.published_at
    # Convert to string if it's a datetime, or parse if it's an ISO string
    if isinstance(published, datetime):
        published_fmt = published.strftime("%Y-%m-%d %H:%M")
    else:
        try:
            published_fmt = datetime.fromisoformat(published).strftime("%Y-%m-%d %H:%M")
        except Exception:
            published_fmt = str(published)
    table.add_row(
        item.title,
        item.source,
        published_fmt,
        f"{item.relevance_score:.2f}" if item.relevance_score is not None else "-",
        f"{item.recency_weight:.2f}" if item.recency_weight is not None else "-",
        f"{item.final_score:.2f}" if item.final_score is not None else "-",
        item.top_relevant_label.replace(RELEVANT_LABEL_SUFFIX, "") if item.top_relevant_label else "-"
    )

console.print(table)

# --- Assessment and Metrics Output ---
if ASSESS_CORRECTNESS_WITH_BIGGER_MODEL:
    # Before the assessment by the larger model, print a headline
    print("\n==============================")
    print("Assessment by larger model: falcon-7B-instruct")
    print("==============================\n")
    # Prepare NewsItem-like dicts for assessment
    pipeline_labels = {item.id: ('RELEVANT' if (item.relevance_score is not None and item.relevance_score > MIN_SCORE) else 'NOT_RELEVANT') for item in news_items}
    model_labels = assess_with_bigger_model(news_items)
    precision, recall, cm = evaluate_pipeline_vs_model(pipeline_labels, model_labels)
    # F1 score
    y_true = [1 if model_labels.get(i) == 'RELEVANT' else 0 for i in pipeline_labels if i in model_labels]
    y_pred = [1 if pipeline_labels.get(i) == 'RELEVANT' else 0 for i in pipeline_labels if i in model_labels]
    f1 = f1_score(y_true, y_pred) if y_true else 0.0
    # Output summary table
    metrics_table = RichTable(title="Retrieval & Filtering Evaluation", box=box.SIMPLE_HEAVY)
    metrics_table.add_column("Metric", style="bold")
    metrics_table.add_column("Value", style="green")
    metrics_table.add_row("Precision", f"{precision:.2f}")
    metrics_table.add_row("Recall", f"{recall:.2f}")
    metrics_table.add_row("F1 Score", f"{f1:.2f}")
    metrics_table.add_row("Confusion Matrix", str(cm))
    console.print(metrics_table)
    # Find false positives/negatives
    false_positives = []
    false_negatives = []
    for item in news_items:
        id = item.id
        model_label = model_labels.get(id)
        pipeline_label = pipeline_labels.get(id)
        if model_label and pipeline_label:
            if model_label == 'NOT_RELEVANT' and pipeline_label == 'RELEVANT':
                false_positives.append(item)
            elif model_label == 'RELEVANT' and pipeline_label == 'NOT_RELEVANT':
                false_negatives.append(item)
    # Output FP/FN tables
    def get_first_n_sentences(text, n=2):
        if not text:
            return ""
        sentences = re.split(r'(?<=[.!?]) +', text)
        return ' '.join(sentences[:n])
    def print_fp_fn_table(items, title):
        if not items:
            console.print(Panel(Text(f"None", style="yellow"), title=title))
            return
        t = RichTable(title=title, box=box.SIMPLE_HEAVY)
        t.add_column("Title", style="bold")
        t.add_column("First Sentences of Body", style="white")
        for item in items:
            t.add_row(item.title, get_first_n_sentences(item.body))
        console.print(t)
    print_fp_fn_table(false_positives, "False Positives (Pipeline said RELEVANT, Model said NOT_RELEVANT)")
    print_fp_fn_table(false_negatives, "False Negatives (Pipeline said NOT_RELEVANT, Model said RELEVANT)") 