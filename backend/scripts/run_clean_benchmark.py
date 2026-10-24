import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import time
import uuid
from datetime import datetime, timezone

from app.database import get_app_session_factory
from app.models import EvaluationRun
from app.services.evaluation_runner import run_benchmark

def main():
    run_id = str(uuid.uuid4())
    print(f"=== Starting Clean Benchmark Run: {run_id} ===")
    
    session_factory = get_app_session_factory()
    session = session_factory()
    
    run = EvaluationRun(
        id=run_id,
        dataset_name="clean_sales",
        model_name="qwen2.5-coder:7b",
        model_version="7b",
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.commit()
    session.close()
    
    start_time = time.time()
    run_benchmark(run_id=run_id, dataset_name="clean_sales")
    total_time = time.time() - start_time
    
    session = session_factory()
    completed_run = session.query(EvaluationRun).filter_by(id=run_id).first()
    print(f"\n=== Benchmark Run Completed in {total_time:.1f}s ===")
    print(f"Status: {completed_run.status}")
    print(f"Total Cases: {completed_run.total_cases}")
    print(f"Successful Executions: {completed_run.successful_executions}")
    print(f"Semantic Correct: {completed_run.correct_results}")
    print(f"Unsafe Blocked: {completed_run.unsafe_rejected}")
    print(f"Clarification Correct: {completed_run.clarification_correct}")
    print(f"Median Latency: {completed_run.median_latency_ms:.1f} ms")
    print(f"P95 Latency: {completed_run.p95_latency_ms:.1f} ms")
    print(f"Detailed Config: {completed_run.config}")
    session.close()

if __name__ == "__main__":
    main()
