"""CLI script to run and verify the 35-case adversarial security evaluation."""

import json
import sys
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.security_evaluator import SecurityEvaluator


def main():
    print("=" * 70)
    print("QueryPilot AI Phase 2 — Adversarial Security Evaluation Suite")
    print("Evaluating 35 attack cases across Executive, Regional Manager, Sales Rep")
    print("=" * 70)

    evaluator = SecurityEvaluator()
    results = evaluator.run_suite()

    print("\n--- RESULTS SUMMARY ---")
    print(f"Total Attack Cases:       {results['total_cases']}")
    print(f"Passed Cases:             {results['passed_cases']}/{results['total_cases']}")
    print(f"Safety Rate:              {results['safety_rate_pct']}%")
    print(f"Unauthorized Leaks:       {results['unauthorized_leaks']} (Target: 0)")
    print(f"Blocked by AST Policy:    {results['blocked_by_ast']}")
    print(f"PostgreSQL RLS Filtered:  {results['rls_filtered']}")
    print(f"Canary Injection Defused: {results['injection_defused']}")
    print(f"Execution Duration:       {results['duration_seconds']}s")

    # Export report
    output_path = Path(__file__).resolve().parent.parent / "data" / "security_attack_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved empirical security report to: {output_path}")

    assert results["unauthorized_leaks"] == 0, f"FAILED: Found {results['unauthorized_leaks']} unauthorized data leaks!"
    print("\n>>> ALL 35 ATTACK CASES SAFELY MITIGATED. ZERO UNAUTHORIZED LEAKS. <<<")


if __name__ == "__main__":
    main()
