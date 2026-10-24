import React, { useState, useEffect, useRef } from 'react';
import { Play, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, Clock, Award, Activity, AlertCircle, RefreshCw, ChevronDown, ChevronRight, Database, Code2, BarChart3 } from 'lucide-react';
import PageHeader from './PageHeader';

export default function BenchmarkRunner() {
  const [runs, setRuns] = useState([]);
  const [activeRun, setActiveRun] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [expandedRef, setExpandedRef] = useState({});
  const pollRef = useRef(null);

  const fetchRuns = async () => {
    try {
      const res = await fetch('/api/v1/evaluations/runs');
      if (res.ok) {
        const data = await res.json();
        setRuns(data || []);
        if (data && data.length > 0 && !activeRun) {
          fetchRunDetails(data[0].id);
        }
      }
    } catch (e) {
      console.error('Failed to load evaluation runs', e);
    }
  };

  const fetchRunDetails = async (runId) => {
    try {
      const res = await fetch(`/api/v1/evaluations/runs/${runId}`);
      if (res.ok) {
        const runData = await res.json();
        setActiveRun(runData);
        if (runData.status === 'running') {
          startPolling(runId);
        }
      }
    } catch (e) {
      console.error('Failed to load run details', e);
    }
  };

  const startPolling = (runId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    setIsRunning(true);
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/evaluations/runs/${runId}`);
        if (res.ok) {
          const updated = await res.json();
          setActiveRun(updated);
          if (updated.status !== 'running') {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setIsRunning(false);
            fetchRuns();
          }
        }
      } catch (err) {
        console.error('Polling error', err);
      }
    }, 2000);
  };

  useEffect(() => {
    fetchRuns();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleStartBenchmark = async () => {
    setIsRunning(true);
    try {
      const res = await fetch('/api/v1/evaluations/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset_name: 'Dataset A (Sales Operations)',
          connection_id: 'default'
        })
      });
      if (res.ok) {
        const newRun = await res.json();
        setActiveRun({ ...newRun, results: [] });
        startPolling(newRun.id);
        fetchRuns();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Failed to start benchmark: ${err.detail || res.statusText}`);
        setIsRunning(false);
      }
    } catch (e) {
      console.error('Benchmark execution error', e);
      setIsRunning(false);
    }
  };

  const toggleRefSql = (id) => {
    setExpandedRef(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const results = activeRun?.results || [];
  const categories = ['all', ...new Set(results.map(r => r.category).filter(Boolean))];

  const filteredResults = selectedCategory === 'all'
    ? results
    : results.filter(r => r.category === selectedCategory);

  // Exact metrics derived strictly from recorded executions
  const totalEvaluated = results.length;
  const totalExpected = activeRun?.total_cases || (isRunning ? 31 : totalEvaluated);

  const executableCases = results.filter(r => r.expected_behavior === 'success');
  const semanticCorrectCount = executableCases.filter(r => r.result_correct).length;
  const execSuccessCount = executableCases.filter(r => r.execution_success).length;

  const safetyCases = results.filter(r => r.expected_behavior === 'reject' || r.category === 'safety');
  const safetyBlockedCount = safetyCases.filter(r => r.policy_outcome === 'rejected' || r.result_correct).length;

  const clarificationCases = results.filter(r => r.expected_behavior === 'clarification');
  const clarificationCorrectCount = clarificationCases.filter(r => r.policy_outcome === 'clarification' || r.result_correct).length;

  const validLatencies = results.map(r => r.latency_ms).filter(v => v != null && !isNaN(v));
  let medianLatency = null;
  let p95Latency = null;
  if (validLatencies.length > 0) {
    const sorted = [...validLatencies].sort((a, b) => a - b);
    medianLatency = Math.round(sorted[Math.floor(sorted.length / 2)]);
    p95Latency = Math.round(sorted[Math.min(Math.floor(sorted.length * 0.95), sorted.length - 1)]);
  } else if (activeRun?.median_latency_ms != null) {
    medianLatency = Math.round(activeRun.median_latency_ms);
    p95Latency = activeRun.p95_latency_ms != null ? Math.round(activeRun.p95_latency_ms) : null;
  }

  const semanticPct = executableCases.length > 0 ? Math.round((semanticCorrectCount / executableCases.length) * 100) : null;
  const execPct = executableCases.length > 0 ? Math.round((execSuccessCount / executableCases.length) * 100) : null;
  const safetyPct = safetyCases.length > 0 ? Math.round((safetyBlockedCount / safetyCases.length) * 100) : null;
  const clarifyPct = clarificationCases.length > 0 ? Math.round((clarificationCorrectCount / clarificationCases.length) * 100) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', width: '100%', maxWidth: '1360px', margin: '0 auto' }}>
      {/* Standardized Executive Page Header */}
      <PageHeader
        icon={BarChart3}
        title="Semantic Accuracy Benchmark (31 Cases)"
        subtitle="Curated 31-case ground-truth test suite measuring semantic SQL correctness, join accuracy, aggregation validity, AST security rejection, and execution latency."
        badge={`${activeRun?.total_cases || 31} Golden Test Cases`}
        badgeType="teal"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {runs.length > 0 && (
              <select
                value={activeRun?.id || ''}
                onChange={(e) => fetchRunDetails(e.target.value)}
                style={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-secondary)',
                  padding: '7px 12px',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.8rem',
                  outline: 'none',
                }}
              >
                {runs.map((r, i) => (
                  <option key={r.id} value={r.id}>
                    Run #{runs.length - i} — {r.status.toUpperCase()} ({r.correct_results}/{r.total_cases || 31} semantic correct)
                  </option>
                ))}
              </select>
            )}

            <button
              className="btn-primary"
              onClick={handleStartBenchmark}
              disabled={isRunning || activeRun?.status === 'running'}
              style={{ padding: '8px 18px', display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {isRunning || activeRun?.status === 'running' ? (
                <>
                  <Activity size={15} className="animate-spin" />
                  <span>Running Suite...</span>
                </>
              ) : (
                <>
                  <Play size={14} fill="currentColor" />
                  <span>Run Full Benchmark Suite</span>
                </>
              )}
            </button>
          </div>
        }
      />

      {/* Meaningful Run Error Banner */}
      {activeRun?.status === 'failed' && (
        <div style={{
          background: 'var(--danger-bg)',
          border: '1px solid var(--danger-border)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem 1.25rem',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          color: '#fca5a5',
          fontSize: '0.88rem'
        }}>
          <AlertCircle size={20} style={{ color: 'var(--danger)', flexShrink: 0 }} />
          <div>
            <strong>Benchmark Run Error:</strong> {activeRun.error_message || 'The benchmark run encountered an unexpected failure.'}
          </div>
        </div>
      )}

      {/* Live Execution Progress Card */}
      {(isRunning || activeRun?.status === 'running') && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.12) 0%, rgba(139, 92, 246, 0.08) 100%)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.9rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-headings)', fontWeight: 600 }}>
              <Activity size={16} className="animate-spin" style={{ color: 'var(--teal-primary)' }} />
              <span>Evaluating Benchmark Test Cases Against Local Ollama & PostgreSQL Target...</span>
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
              {totalEvaluated} / {totalExpected} ({totalExpected > 0 ? Math.round((totalEvaluated / totalExpected) * 100) : 0}%)
            </span>
          </div>

          <div style={{
            width: '100%',
            height: '8px',
            background: 'var(--bg-secondary)',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${totalExpected > 0 ? (totalEvaluated / totalExpected) * 100 : 0}%`,
              height: '100%',
              background: 'var(--accent-gradient)',
              borderRadius: '4px',
              transition: 'width 0.4s ease'
            }} />
          </div>
        </div>
      )}

      {/* 5 Distinct Metric Cards — Clearly defined denominators */}
      <div className="benchmark-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <div className="stat-card">
          <div className="stat-label">Semantic Correctness</div>
          <div className="stat-value" style={{ color: semanticPct != null ? (semanticPct >= 80 ? '#10b981' : '#f59e0b') : 'var(--text-muted)' }}>
            {semanticPct != null ? `${semanticPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {executableCases.length > 0 ? `${semanticCorrectCount} of ${executableCases.length} analytical answers match ground truth rows` : 'Pending analytical cases'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Execution Success Rate</div>
          <div className="stat-value" style={{ color: execPct != null ? '#38bdf8' : 'var(--text-muted)' }}>
            {execPct != null ? `${execPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {executableCases.length > 0 ? `${execSuccessCount} of ${executableCases.length} queries executed cleanly on DB` : 'Pending execution'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Security Enforcement</div>
          <div className="stat-value" style={{ color: safetyPct != null ? '#a855f7' : 'var(--text-muted)' }}>
            {safetyPct != null ? `${safetyPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {safetyCases.length > 0 ? `${safetyBlockedCount} of ${safetyCases.length} attacks rejected prior to execution` : 'Pending safety tests'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Clarification Handling</div>
          <div className="stat-value" style={{ color: clarifyPct != null ? '#60a5fa' : 'var(--text-muted)' }}>
            {clarifyPct != null ? `${clarifyPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {clarificationCases.length > 0 ? `${clarificationCorrectCount} of ${clarificationCases.length} ambiguous queries handled` : 'Pending clarification test'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Median Latency</div>
          <div className="stat-value" style={{ color: medianLatency != null ? '#f59e0b' : 'var(--text-muted)' }}>
            {medianLatency != null ? `${medianLatency}ms` : '—'}
          </div>
          <div className="stat-sub">
            {p95Latency ? `P95 Latency: ${p95Latency}ms` : 'Inference + AST + DB execution'}
          </div>
        </div>
      </div>

      {/* Category Filter Chips */}
      {categories.length > 1 && (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="sample-label">Category:</span>
          {categories.map((cat, idx) => {
            const count = cat === 'all' ? results.length : results.filter(r => r.category === cat).length;
            return (
              <button
                key={idx}
                className={`prompt-chip ${selectedCategory === cat ? 'active' : ''}`}
                style={{
                  background: selectedCategory === cat ? 'var(--accent-primary)' : 'var(--bg-surface)',
                  color: selectedCategory === cat ? 'white' : 'var(--text-secondary)',
                  border: selectedCategory === cat ? '1px solid var(--teal-primary)' : '1px solid var(--border-card)'
                }}
                onClick={() => setSelectedCategory(cat)}
              >
                {cat} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Test Cases Results Table */}
      <div className="data-table-card">
        <div className="table-controls">
          <span className="table-stats">
            <strong>{filteredResults.length}</strong> of <strong>{totalExpected}</strong> Test Cases Recorded
          </span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Target DB: <strong>querypilot_target</strong> • Model: <strong>{activeRun?.model_name || 'qwen2.5-coder:7b'}</strong>
          </span>
        </div>

        <div className="table-wrapper">
          <table className="styled-table">
            <thead>
              <tr>
                <th style={{ width: '35px' }}>#</th>
                <th style={{ width: '90px' }}>Evaluation</th>
                <th>Scenario / Question & SQL Inspection</th>
                <th style={{ width: '95px' }}>Category</th>
                <th style={{ width: '100px' }}>Expected</th>
                <th style={{ width: '120px' }}>Actual Outcome</th>
                <th style={{ width: '75px' }}>Latency</th>
              </tr>
            </thead>
            <tbody>
              {filteredResults.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--text-muted)' }}>
                    {isRunning || activeRun?.status === 'running'
                      ? 'Executing test cases against local model and PostgreSQL... Results will appear as each test completes.'
                      : activeRun?.status === 'failed'
                        ? `Benchmark run failed: ${activeRun.error_message}`
                        : 'No benchmark run loaded. Click "Run Full Benchmark Suite" to start evaluating the 31 cases.'}
                  </td>
                </tr>
              ) : (
                filteredResults.map((tc, idx) => {
                  const isSafety = tc.expected_behavior === 'reject';
                  const isClarify = tc.expected_behavior === 'clarification';
                  const isAnalytical = tc.expected_behavior === 'success';

                  // Explicit status determination
                  let statusBadge = null;
                  if (isSafety) {
                    if (tc.policy_outcome === 'rejected' || tc.result_correct) {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#a855f7' }}>
                          <CheckCircle2 size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>BLOCKED</span>
                        </div>
                      );
                    } else {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--danger)' }}>
                          <XCircle size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>UNSAFE</span>
                        </div>
                      );
                    }
                  } else if (isClarify) {
                    if (tc.policy_outcome === 'clarification' || tc.result_correct) {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#60a5fa' }}>
                          <CheckCircle2 size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>CLARIFIED</span>
                        </div>
                      );
                    } else {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--danger)' }}>
                          <XCircle size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>FAIL</span>
                        </div>
                      );
                    }
                  } else {
                    // Analytical query
                    if (tc.result_correct) {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--success)' }}>
                          <CheckCircle2 size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>CORRECT</span>
                        </div>
                      );
                    } else if (tc.execution_success) {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#f59e0b' }}>
                          <AlertTriangle size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>MISMATCH</span>
                        </div>
                      );
                    } else {
                      statusBadge = (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--danger)' }}>
                          <XCircle size={15} />
                          <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>ERROR</span>
                        </div>
                      );
                    }
                  }

                  const isExpanded = expandedRef[tc.id || idx];

                  return (
                    <tr key={tc.id || idx}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {idx + 1}
                      </td>
                      <td>{statusBadge}</td>
                      <td style={{ maxWidth: '460px' }}>
                        <div style={{ fontWeight: 500, color: 'var(--text-headings)', fontSize: '0.85rem' }}>{tc.question}</div>
                        {tc.generated_sql && (
                          <div style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.72rem',
                            color: 'var(--teal-primary)',
                            marginTop: '4px',
                            background: 'var(--bg-secondary)',
                            border: '1px solid var(--border-card)',
                            padding: '4px 8px',
                            borderRadius: '4px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}>
                            <span style={{ color: 'var(--text-muted)', marginRight: '6px' }}>Generated:</span>
                            {tc.generated_sql}
                          </div>
                        )}
                        {tc.expected_sql && (
                          <div style={{ marginTop: '4px' }}>
                            <button
                              onClick={() => toggleRefSql(tc.id || idx)}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                fontSize: '0.7rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '0'
                              }}
                            >
                              {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                              {isExpanded ? 'Hide Reference SQL' : 'View Verified Reference SQL'}
                            </button>
                            {isExpanded && (
                              <div style={{
                                fontFamily: 'var(--font-mono)',
                                fontSize: '0.7rem',
                                color: '#059669',
                                marginTop: '4px',
                                background: 'rgba(16, 185, 129, 0.08)',
                                border: '1px solid rgba(16, 185, 129, 0.2)',
                                padding: '6px 8px',
                                borderRadius: '4px',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-all'
                              }}>
                                {tc.expected_sql}
                              </div>
                            )}
                          </div>
                        )}
                        {tc.error_message && (
                          <div style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: '3px' }}>
                            {tc.error_message}
                          </div>
                        )}
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.7rem',
                          padding: '2px 7px',
                          borderRadius: '4px',
                          background: 'var(--bg-elevated)',
                          color: 'var(--text-secondary)'
                        }}>
                          {tc.category || 'general'}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.78rem' }}>
                        {isSafety ? (
                          <span style={{ color: '#a855f7', fontWeight: 500 }}>Security Block</span>
                        ) : isClarify ? (
                          <span style={{ color: '#60a5fa', fontWeight: 500 }}>Clarification</span>
                        ) : (
                          <span style={{ color: 'var(--success)', fontWeight: 500 }}>Valid Query</span>
                        )}
                      </td>
                      <td style={{ fontSize: '0.78rem' }}>
                        {tc.policy_outcome === 'rejected' ? (
                          <span style={{ color: '#a855f7' }}>Blocked by Policy</span>
                        ) : tc.policy_outcome === 'executed' ? (
                          <span style={{ color: tc.result_correct ? 'var(--success)' : '#f59e0b' }}>
                            {tc.result_correct ? 'Semantic Match' : 'Semantic Mismatch'}
                          </span>
                        ) : tc.policy_outcome === 'semantic_mismatch' ? (
                          <span style={{ color: '#f59e0b', fontWeight: 500 }}>Semantic Mismatch</span>
                        ) : tc.policy_outcome === 'clarification' ? (
                          <span style={{ color: '#60a5fa' }}>Clarification Asked</span>
                        ) : tc.policy_outcome === 'allowed_unsafe' ? (
                          <span style={{ color: 'var(--danger)', fontWeight: 600 }}>Unsafe Allowed</span>
                        ) : tc.policy_outcome === 'execution_error' ? (
                          <span style={{ color: 'var(--danger)' }}>Execution Error</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>{tc.policy_outcome || '—'}</span>
                        )}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        {tc.latency_ms ? `${Math.round(tc.latency_ms)}ms` : '—'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
