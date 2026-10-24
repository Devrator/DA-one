"""Automated tests for Benchmark Evaluation Runner."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.database import get_app_session_factory
from app.models import EvaluationRun, EvaluationResult
from app.services.evaluation_runner import run_benchmark, CLEAN_SALES_BENCHMARK


@pytest.fixture
def db_session():
    factory = get_app_session_factory()
    session = factory()
    yield session
    session.close()


def test_benchmark_dataset_normalization(db_session):
    """Test that various dataset naming variations are accepted."""
    test_names = [
        "clean_sales",
        "Dataset A (Sales Operations)",
        "Dataset A",
        "sales",
        "default",
    ]
    for name in test_names:
        run = EvaluationRun(
            dataset_name=name,
            model_name="mock_model",
            status="running",
        )
        db_session.add(run)
        db_session.commit()

        # Run with max_cases=0 or check dataset rejection
        with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls, \
             patch("app.services.evaluation_runner.get_default_target_engine") as mock_engine, \
             patch("app.services.evaluation_runner.SchemaService.discover_schema") as mock_disc:
            
            mock_llm = MagicMock()
            mock_llm.check_health.return_value = {"status": "healthy"}
            mock_llm_cls.return_value = mock_llm

            with patch("app.database.check_db_health", return_value={"status": "healthy"}):
                mock_disc.return_value = MagicMock()
                run_benchmark(run.id, dataset_name=name, max_cases=1)

        db_session.refresh(run)
        assert run.status == "completed", f"Dataset '{name}' should be accepted, got status={run.status}, err={run.error_message}"
        assert run.error_message is None


def test_benchmark_successful_run(db_session):
    """Test a successful benchmark run with multiple categories."""
    run = EvaluationRun(
        dataset_name="clean_sales",
        model_name="test_model",
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls, \
         patch("app.services.evaluation_runner.SQLGenerator") as mock_gen_cls, \
         patch("app.services.evaluation_runner.QueryExecutor") as mock_exec_cls, \
         patch("app.services.evaluation_runner.SchemaService.discover_schema"), \
         patch("app.database.check_db_health", return_value={"status": "healthy"}):

        mock_llm = MagicMock()
        mock_llm.check_health.return_value = {"status": "healthy"}
        mock_llm_cls.return_value = mock_llm

        # Generator returns valid results
        mock_gen = MagicMock()
        mock_gen.generate.return_value = MagicMock(
            success=True,
            sql="SELECT count(*) FROM sales.customers",
            needs_clarification=False,
            repair_attempts=0,
            error=None
        )
        mock_gen_cls.return_value = mock_gen

        # Executor returns success
        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(
            success=True,
            error=None,
            row_count=1,
            columns=["count"],
            data=[{"count": 30}],
            execution_time_ms=10.0
        )
        mock_exec_cls.return_value = mock_exec
        mock_exec_cls.from_settings.return_value = mock_exec

        # Run 3 cases
        run_benchmark(run.id, dataset_name="clean_sales", max_cases=3)

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.total_cases == 3
    assert run.successful_executions == 3
    assert run.correct_results == 3
    assert run.median_latency_ms is not None

    results = db_session.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
    assert len(results) == 3
    assert all(r.result_correct is True for r in results)


def test_benchmark_failed_case(db_session):
    """Test handling of a failed query execution within a benchmark run."""
    run = EvaluationRun(
        dataset_name="clean_sales",
        model_name="test_model",
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls, \
         patch("app.services.evaluation_runner.SQLGenerator") as mock_gen_cls, \
         patch("app.services.evaluation_runner.QueryExecutor") as mock_exec_cls, \
         patch("app.services.evaluation_runner.SchemaService.discover_schema"), \
         patch("app.database.check_db_health", return_value={"status": "healthy"}):

        mock_llm = MagicMock()
        mock_llm.check_health.return_value = {"status": "healthy"}
        mock_llm_cls.return_value = mock_llm

        mock_gen = MagicMock()
        mock_gen.generate.return_value = MagicMock(
            success=True,
            sql="SELECT invalid_col FROM sales.customers",
            needs_clarification=False,
            repair_attempts=0,
            error=None
        )
        mock_gen_cls.return_value = mock_gen

        # Executor simulates SQL error
        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(
            success=False,
            error="column 'invalid_col' does not exist",
            row_count=0,
            data=[],
            execution_time_ms=5.0
        )
        mock_exec_cls.return_value = mock_exec
        mock_exec_cls.from_settings.return_value = mock_exec

        run_benchmark(run.id, dataset_name="clean_sales", max_cases=1)

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.total_cases == 1
    assert run.successful_executions == 0
    assert run.correct_results == 0

    results = db_session.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
    assert len(results) == 1
    assert results[0].execution_success is False
    assert results[0].result_correct is False
    assert "invalid_col" in results[0].error_message


def test_benchmark_unavailable_model(db_session):
    """Test run failure when LLM model provider is unavailable."""
    run = EvaluationRun(
        dataset_name="clean_sales",
        model_name="offline_model",
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm.check_health.return_value = {
            "status": "unhealthy",
            "error": "Connection refused to Ollama at http://localhost:11434"
        }
        mock_llm_cls.return_value = mock_llm

        run_benchmark(run.id, dataset_name="clean_sales")

    db_session.refresh(run)
    assert run.status == "failed"
    assert "Model provider unavailable" in run.error_message
    assert run.completed_at is not None

    results = db_session.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
    assert len(results) == 0


def test_benchmark_database_error(db_session):
    """Test run failure when target database is unreachable."""
    run = EvaluationRun(
        dataset_name="clean_sales",
        model_name="test_model",
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls, \
         patch("app.database.check_db_health") as mock_db_check:

        mock_llm = MagicMock()
        mock_llm.check_health.return_value = {"status": "healthy"}
        mock_llm_cls.return_value = mock_llm

        mock_db_check.return_value = {
            "status": "unhealthy",
            "error": "could not connect to server: Connection refused"
        }

        run_benchmark(run.id, dataset_name="clean_sales")

    db_session.refresh(run)
    assert run.status == "failed"
    assert "Target database unavailable" in run.error_message
    assert run.completed_at is not None


def test_benchmark_interrupted_run(db_session):
    """Test that an interrupted run updates status to failed and preserves completed cases."""
    run = EvaluationRun(
        dataset_name="clean_sales",
        model_name="test_model",
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    with patch("app.services.evaluation_runner.LLMProvider.from_settings") as mock_llm_cls, \
         patch("app.services.evaluation_runner.SQLGenerator") as mock_gen_cls, \
         patch("app.services.evaluation_runner.QueryExecutor") as mock_exec_cls, \
         patch("app.services.evaluation_runner.SchemaService.discover_schema"), \
         patch("app.database.check_db_health", return_value={"status": "healthy"}):

        mock_llm = MagicMock()
        mock_llm.check_health.return_value = {"status": "healthy"}
        mock_llm_cls.return_value = mock_llm

        # 1st call succeeds, 2nd call raises KeyboardInterrupt
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            MagicMock(
                success=True,
                sql="SELECT * FROM sales.customers",
                needs_clarification=False,
                repair_attempts=0,
                error=None
            ),
            KeyboardInterrupt("Simulated task termination")
        ]
        mock_gen_cls.return_value = mock_gen

        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(
            success=True,
            error=None,
            row_count=10,
            execution_time_ms=5.0
        )
        mock_exec_cls.return_value = mock_exec
        mock_exec_cls.from_settings.return_value = mock_exec

        with pytest.raises(KeyboardInterrupt):
            run_benchmark(run.id, dataset_name="clean_sales", max_cases=3)

    db_session.refresh(run)
    assert run.status == "failed"
    assert "interrupted" in run.error_message.lower()

    # The 1st case evaluated before the interrupt was persisted
    results = db_session.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
    assert len(results) == 1
    assert results[0].result_correct is True
