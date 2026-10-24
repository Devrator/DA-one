"""CLI script to run and verify the 50-scenario multi-turn conversation evaluation."""

import json
import sys
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.conversation_evaluator import ConversationEvaluator


def main():
    print("=" * 70)
    print("QueryPilot AI Phase 2 — 50-Scenario Multi-Turn Conversation Benchmark")
    print("Evaluating 50 conversation scenarios (150 turns total) with persistent session context")
    print("=" * 70)

    # Allow limiting runs via CLI arg if needed
    limit = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])
        print(f"Running on first {limit} scenarios for validation...")

    evaluator = ConversationEvaluator()
    results = evaluator.run_suite(limit=limit)

    print("\n--- RESULTS SUMMARY ---")
    print(f"Total Scenarios Evaluated:     {results['total_scenarios']}")
    print(f"Fully Passed Scenarios:       {results['fully_passed_scenarios']}/{results['total_scenarios']}")
    print(f"Scenario Accuracy:            {results['scenario_accuracy_pct']}%")
    print(f"Total Conversation Turns:     {results['total_turns']}")
    print(f"Passed Turns:                 {results['passed_turns']}/{results['total_turns']}")
    print(f"Turn Accuracy:                {results['turn_accuracy_pct']}%")
    print(f"Clarification Accuracy Rate:  {results['clarification_rate_pct']}%")
    print(f"Execution Failures:           {results['execution_failures']}")
    print(f"Security Boundary Failures:   {results['security_failures']} (Target: 0)")
    print(f"Median Turn Latency:          {results['median_latency_ms']} ms")
    print(f"Total Execution Duration:     {results['duration_seconds']}s")

    # Export report
    output_path = Path(__file__).resolve().parent.parent / "data" / "conversations_benchmark_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved empirical conversation benchmark report to: {output_path}")

    assert results["security_failures"] == 0, f"FAILED: {results['security_failures']} security boundary failures detected!"
    print("\n>>> MULTI-TURN CONVERSATION BENCHMARK EVALUATED AND RECORDED. <<<")


if __name__ == "__main__":
    main()
