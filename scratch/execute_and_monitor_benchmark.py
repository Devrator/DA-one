"""Trigger and monitor complete 31-case evaluation benchmark."""

import time
import httpx
import json

BASE_URL = "http://localhost:8001/api/v1"

def run_suite():
    client = httpx.Client(timeout=60)
    print("Initiating evaluation benchmark run...")
    start_resp = client.post(
        f"{BASE_URL}/evaluations/runs",
        json={"dataset_name": "clean_sales", "connection_id": "default"}
    )
    if start_resp.status_code != 200:
        print(f"Failed to start run: {start_resp.status_code} {start_resp.text}")
        return

    run_data = start_resp.json()
    run_id = run_data["id"]
    print(f"Benchmark started: Run ID = {run_id}")

    last_count = 0
    while True:
        time.sleep(3)
        poll_resp = client.get(f"{BASE_URL}/evaluations/runs/{run_id}")
        if poll_resp.status_code != 200:
            print(f"Polling error: {poll_resp.status_code}")
            continue

        detail = poll_resp.json()
        status = detail["status"]
        results = detail.get("results", [])
        curr_count = len(results)

        if curr_count > last_count:
            for r in results[last_count:]:
                behavior = r["expected_behavior"]
                is_correct = r["result_correct"]
                q = r["question"][:55]
                outcome = r["policy_outcome"]
                lat = f"{round(r['latency_ms'])}ms" if r.get("latency_ms") else "N/A"
                print(f"[{len(results):2d}/31] {outcome:18s} | Correct: {str(is_correct):5s} | {lat:7s} | {q}")
            last_count = curr_count

        if status in ("completed", "failed"):
            print(f"\n==========================================")
            print(f"Benchmark finished with status: {status.upper()}")
            print(f"Config / Metrics Breakdown:")
            print(json.dumps(detail.get("config", {}), indent=2))
            print(f"Successful Executions: {detail.get('successful_executions')}")
            print(f"Semantic Correct:      {detail.get('correct_results')}")
            print(f"Unsafe Rejected:       {detail.get('unsafe_rejected')}")
            print(f"Clarifications:        {detail.get('clarification_correct')}")
            print(f"Repairs Succeeded:     {detail.get('repair_successes')}")
            print(f"Median Latency:        {detail.get('median_latency_ms')} ms")
            print(f"P95 Latency:           {detail.get('p95_latency_ms')} ms")
            if detail.get("error_message"):
                print(f"Error Message:         {detail.get('error_message')}")
            print(f"==========================================")
            break

if __name__ == "__main__":
    run_suite()
