#!/usr/bin/env python3
"""
Lead Classifier Evaluation Script

Runs sample leads through the classifier and reports accuracy against labeled expectations.
Outputs a detailed report with per-lead results and aggregate metrics.

Usage:
    python run_eval.py                    # Run against local classifier service
    python run_eval.py --url http://...   # Run against custom endpoint
    python run_eval.py --dry-run          # Show what would be evaluated without calling API
    python run_eval.py --output report.json  # Save detailed results to file
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import box

console = Console()

DEFAULT_CLASSIFIER_URL = "http://localhost:8001"
SAMPLE_LEADS_PATH = Path(__file__).parent.parent / "data" / "sample_leads.json"


def load_sample_leads() -> list[dict]:
    """Load sample leads from JSON file."""
    with open(SAMPLE_LEADS_PATH) as f:
        return json.load(f)


async def classify_lead(client: httpx.AsyncClient, base_url: str, lead: dict) -> dict:
    """Send a lead to the classifier and return the result."""
    payload = {
        "lead": {
            "name": lead["name"],
            "email": lead["email"],
            "company": lead.get("company"),
            "message": lead["message"],
            "source": lead.get("source", "eval_script")
        },
        "include_draft_reply": False
    }
    
    response = await client.post(
        f"{base_url}/classify",
        json=payload,
        timeout=60.0
    )
    response.raise_for_status()
    return response.json()


async def run_evaluation(
    base_url: str,
    leads: list[dict],
    max_concurrent: int = 3
) -> list[dict]:
    """Run evaluation on all leads with progress tracking."""
    results = []
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_lead(lead: dict) -> dict:
        async with semaphore:
            start_time = time.time()
            try:
                async with httpx.AsyncClient() as client:
                    result = await classify_lead(client, base_url, lead)
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    
                    predicted = result["classification"]["classification"]
                    expected = lead["expected_classification"]
                    
                    return {
                        "lead_id": lead["id"],
                        "name": lead["name"],
                        "expected": expected,
                        "predicted": predicted,
                        "correct": predicted == expected,
                        "confidence": result["classification"]["confidence_score"],
                        "predicted_intent": result["classification"]["intent"],
                        "expected_intent": lead["expected_intent"],
                        "reasoning": result["classification"]["reasoning"],
                        "elapsed_ms": elapsed_ms,
                        "error": None
                    }
            except Exception as e:
                return {
                    "lead_id": lead["id"],
                    "name": lead["name"],
                    "expected": lead["expected_classification"],
                    "predicted": None,
                    "correct": False,
                    "confidence": None,
                    "predicted_intent": None,
                    "expected_intent": lead["expected_intent"],
                    "reasoning": None,
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                    "error": str(e)
                }
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Evaluating leads...", total=len(leads))
        
        tasks = [process_lead(lead) for lead in leads]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            progress.advance(task)
    
    results.sort(key=lambda x: x["lead_id"])
    return results


def calculate_metrics(results: list[dict]) -> dict:
    """Calculate evaluation metrics."""
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    errors = sum(1 for r in results if r["error"])
    
    classifications = ["hot", "warm", "cold", "spam"]
    per_class = {}
    
    for cls in classifications:
        class_results = [r for r in results if r["expected"] == cls]
        if class_results:
            class_correct = sum(1 for r in class_results if r["correct"])
            per_class[cls] = {
                "total": len(class_results),
                "correct": class_correct,
                "accuracy": class_correct / len(class_results) if class_results else 0
            }
    
    confusion = {expected: {predicted: 0 for predicted in classifications + [None]} 
                 for expected in classifications}
    for r in results:
        if r["expected"] in confusion:
            confusion[r["expected"]][r["predicted"]] += 1
    
    confidences = [r["confidence"] for r in results if r["confidence"] is not None]
    correct_confidences = [r["confidence"] for r in results if r["correct"] and r["confidence"]]
    incorrect_confidences = [r["confidence"] for r in results if not r["correct"] and r["confidence"]]
    
    latencies = [r["elapsed_ms"] for r in results if r["error"] is None]
    
    return {
        "total_leads": total,
        "correct_predictions": correct,
        "errors": errors,
        "overall_accuracy": correct / total if total > 0 else 0,
        "per_class_metrics": per_class,
        "confusion_matrix": confusion,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
        "avg_confidence_correct": sum(correct_confidences) / len(correct_confidences) if correct_confidences else 0,
        "avg_confidence_incorrect": sum(incorrect_confidences) / len(incorrect_confidences) if incorrect_confidences else 0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0)
    }


def print_results(results: list[dict], metrics: dict):
    """Print formatted evaluation results."""
    console.print()
    
    console.print(Panel.fit(
        f"[bold]Lead Classifier Evaluation Results[/bold]\n"
        f"Evaluated: {metrics['total_leads']} leads | "
        f"Correct: {metrics['correct_predictions']} | "
        f"Errors: {metrics['errors']}",
        title="Summary"
    ))
    
    table = Table(title="Per-Lead Results", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Name", width=20)
    table.add_column("Expected", width=8)
    table.add_column("Predicted", width=8)
    table.add_column("Conf", width=6)
    table.add_column("Status", width=8)
    table.add_column("Latency", width=8)
    
    for r in results:
        status = "[green]OK[/green]" if r["correct"] else (
            "[red]ERROR[/red]" if r["error"] else "[yellow]WRONG[/yellow]"
        )
        predicted = r["predicted"] or "N/A"
        confidence = f"{r['confidence']:.0%}" if r["confidence"] else "N/A"
        latency = f"{r['elapsed_ms']}ms"
        
        table.add_row(
            str(r["lead_id"]),
            r["name"][:20],
            r["expected"],
            predicted,
            confidence,
            status,
            latency
        )
    
    console.print(table)
    
    console.print()
    accuracy_table = Table(title="Accuracy by Classification", box=box.ROUNDED)
    accuracy_table.add_column("Class", style="bold")
    accuracy_table.add_column("Total", justify="right")
    accuracy_table.add_column("Correct", justify="right")
    accuracy_table.add_column("Accuracy", justify="right")
    
    for cls, data in metrics["per_class_metrics"].items():
        accuracy_pct = f"{data['accuracy']:.1%}"
        color = "green" if data['accuracy'] >= 0.8 else ("yellow" if data['accuracy'] >= 0.6 else "red")
        accuracy_table.add_row(
            cls.upper(),
            str(data["total"]),
            str(data["correct"]),
            f"[{color}]{accuracy_pct}[/{color}]"
        )
    
    console.print(accuracy_table)
    
    console.print()
    confusion_table = Table(title="Confusion Matrix", box=box.ROUNDED)
    confusion_table.add_column("Expected↓ / Predicted→", style="bold")
    for cls in ["hot", "warm", "cold", "spam"]:
        confusion_table.add_column(cls.upper(), justify="center")
    
    for expected in ["hot", "warm", "cold", "spam"]:
        row = [expected.upper()]
        for predicted in ["hot", "warm", "cold", "spam"]:
            count = metrics["confusion_matrix"][expected][predicted]
            if expected == predicted and count > 0:
                row.append(f"[green]{count}[/green]")
            elif count > 0:
                row.append(f"[red]{count}[/red]")
            else:
                row.append("-")
        confusion_table.add_row(*row)
    
    console.print(confusion_table)
    
    console.print()
    overall_color = "green" if metrics['overall_accuracy'] >= 0.8 else ("yellow" if metrics['overall_accuracy'] >= 0.6 else "red")
    console.print(Panel.fit(
        f"[bold]Overall Accuracy:[/bold] [{overall_color}]{metrics['overall_accuracy']:.1%}[/{overall_color}]\n"
        f"[bold]Avg Confidence:[/bold] {metrics['avg_confidence']:.1%}\n"
        f"  - Correct predictions: {metrics['avg_confidence_correct']:.1%}\n"
        f"  - Incorrect predictions: {metrics['avg_confidence_incorrect']:.1%}\n"
        f"[bold]Latency:[/bold] avg={metrics['avg_latency_ms']:.0f}ms, p95={metrics['p95_latency_ms']:.0f}ms",
        title="Metrics Summary"
    ))
    
    incorrect = [r for r in results if not r["correct"] and not r["error"]]
    if incorrect:
        console.print()
        console.print("[bold yellow]Misclassified Leads:[/bold yellow]")
        for r in incorrect:
            console.print(f"  • Lead #{r['lead_id']} ({r['name']}): expected {r['expected']}, got {r['predicted']}")
            if r["reasoning"]:
                console.print(f"    Reasoning: {r['reasoning'][:100]}...")


def save_report(results: list[dict], metrics: dict, output_path: str):
    """Save detailed report to JSON file."""
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": metrics,
        "results": results
    }
    
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    console.print(f"\n[dim]Detailed report saved to: {output_path}[/dim]")


def print_dry_run(leads: list[dict]):
    """Print what would be evaluated without calling the API."""
    console.print(Panel.fit(
        f"[bold]Dry Run Mode[/bold]\n"
        f"Would evaluate {len(leads)} leads",
        title="Dry Run"
    ))
    
    table = Table(title="Sample Leads to Evaluate", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Name", width=20)
    table.add_column("Company", width=20)
    table.add_column("Expected", width=8)
    table.add_column("Message Preview", width=40)
    
    for lead in leads:
        table.add_row(
            str(lead["id"]),
            lead["name"],
            lead.get("company") or "N/A",
            lead["expected_classification"],
            lead["message"][:40] + "..."
        )
    
    console.print(table)
    
    console.print()
    by_class = {}
    for lead in leads:
        cls = lead["expected_classification"]
        by_class[cls] = by_class.get(cls, 0) + 1
    
    console.print("[bold]Distribution:[/bold]")
    for cls, count in sorted(by_class.items()):
        console.print(f"  • {cls}: {count}")


async def main():
    parser = argparse.ArgumentParser(description="Evaluate lead classifier accuracy")
    parser.add_argument(
        "--url",
        default=DEFAULT_CLASSIFIER_URL,
        help=f"Classifier service URL (default: {DEFAULT_CLASSIFIER_URL})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be evaluated without calling API"
    )
    parser.add_argument(
        "--output",
        help="Save detailed results to JSON file"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent requests (default: 3)"
    )
    
    args = parser.parse_args()
    
    console.print("[bold blue]Lead Classifier Evaluation[/bold blue]")
    console.print(f"Classifier URL: {args.url}")
    console.print()
    
    try:
        leads = load_sample_leads()
        console.print(f"Loaded {len(leads)} sample leads from {SAMPLE_LEADS_PATH}")
    except FileNotFoundError:
        console.print(f"[red]Error: Sample leads file not found at {SAMPLE_LEADS_PATH}[/red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error: Invalid JSON in sample leads file: {e}[/red]")
        sys.exit(1)
    
    if args.dry_run:
        print_dry_run(leads)
        return
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{args.url}/health", timeout=5.0)
            health = response.json()
            console.print(f"Classifier healthy: {health['provider']}/{health['model']}")
        except Exception as e:
            console.print(f"[red]Error: Cannot connect to classifier at {args.url}[/red]")
            console.print(f"[red]Details: {e}[/red]")
            console.print("\n[yellow]Make sure the classifier service is running:[/yellow]")
            console.print("  docker-compose up -d lead-classifier")
            console.print("  # or")
            console.print("  cd services/lead-classifier && python main.py")
            sys.exit(1)
    
    console.print()
    results = await run_evaluation(args.url, leads, args.concurrency)
    metrics = calculate_metrics(results)
    
    print_results(results, metrics)
    
    if args.output:
        save_report(results, metrics, args.output)
    
    exit_code = 0 if metrics["overall_accuracy"] >= 0.7 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
