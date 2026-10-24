import React, { useState, useEffect, useRef } from 'react';
import { Play, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, Clock, Award, Activity, AlertCircle, RefreshCw } from 'lucide-react';

export default function BenchmarkRunner() {
  const [runs, setRuns] = useState([]);
  const [activeRun, setActiveRun] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState('all');
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

  const results = activeRun?.results || [];
  const categories = ['all', ...new Set(results.map(r => r.category).filter(Boolean))];

  const filteredResults = selectedCategory === 'all'
    ? results
    : results.filter(r => r.category === selectedCategory);

  // Exact metrics derived strictly from recorded executions
  const totalEvaluated = results.length;
  const totalExpected = activeRun?.total_cases || (isRunning ? 31 : totalEvaluated);
  const correctCount = results.filter(r => r.result_correct).length;

  const executableCases = results.filter(r => r.expected_behavior === 'success');
  const execSuccessCount = executableCases.filter(r => r.execution_success).length;

  const safetyCases = results.filter(r => r.expected_behavior === 'reject' || r.category === 'safety');
  const safetyBlockedCount = safetyCases.filter(r => r.policy_outcome === 'rejected' || r.result_correct).length;

  const validLatencies = results.map(r => r.latency_ms).filter(v => v != null && !isNaN(v));
  let medianLatency = null;
  if (totalEvaluated > 0) {
    if (validLatencies.length > 0) {
      const sorted = [...validLatencies].sort((a, b) => a - b);
      medianLatency = Math.round(sorted[Math.floor(sorted.length / 2)]);
    } else if (activeRun?.median_latency_ms != null) {
      medianLatency = Math.round(activeRun.median_latency_ms);
    }
  }

  const accuracyPct = totalEvaluated > 0 ? Math.round((correctCount / totalEvaluated) * 100) : null;
  const execPct = executableCases.length > 0 ? Math.round((execSuccessCount / executableCases.length) * 100) : null;
  const safetyPct = safetyCases.length > 0 ? Math.round((safetyBlockedCount / safetyCases.length) * 100) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header and Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff' }}>
            Empirical Evaluation Benchmark
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Curated 31-case ground-truth test suite measuring accuracy, AST validity, latency, and security rejection.
          </p>
        </div>

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
                  Run #{runs.length - i} — {r.status.toUpperCase()} ({r.correct_results}/{r.total_cases || 31} passed)
                </option>
              ))}
            </select>
          )}

          <button
            className="btn-primary"
            onClick={handleStartBenchmark}
            disabled={isRunning || activeRun?.status === 'running'}
            style={{ padding: '8px 20px' }}
          >
            {isRunning || activeRun?.status === 'running' ? (
              <>
                <Activity size={16} className="animate-spin" />
                Running Suite...
              </>
            ) : (
              <>
                <Play size={16} fill="currentColor" />
                Run Full Benchmark Suite
              </>
            )}
          </button>
        </div>
      </div>

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
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#ffffff', fontWeight: 600 }}>
              <Activity size={16} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
              <span>Evaluating Benchmark Test Cases...</span>
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

      {/* KPI Cards — Purely computed from real recorded executions */}
      <div className="benchmark-grid">
        <div className="stat-card">
          <div className="stat-label">Evaluation Accuracy</div>
          <div className="stat-value" style={{ color: accuracyPct != null ? (accuracyPct >= 70 ? '#10b981' : '#f59e0b') : 'var(--text-muted)' }}>
            {accuracyPct != null ? `${accuracyPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {totalEvaluated > 0 ? `${correctCount} of ${totalEvaluated} evaluated passed` : 'No cases evaluated yet'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Execution Rate</div>
          <div className="stat-value" style={{ color: execPct != null ? '#38bdf8' : 'var(--text-muted)' }}>
            {execPct != null ? `${execPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {executableCases.length > 0 ? `${execSuccessCount} of ${executableCases.length} executable queries ran without error` : 'No executable queries evaluated'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Safety Enforcement</div>
          <div className="stat-value" style={{ color: safetyPct != null ? '#a855f7' : 'var(--text-muted)' }}>
            {safetyPct != null ? `${safetyPct}%` : '—'}
          </div>
          <div className="stat-sub">
            {safetyCases.length > 0 ? `${safetyBlockedCount} of ${safetyCases.length} adversarial/injection tests blocked` : 'No safety cases evaluated'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Median Latency</div>
          <div className="stat-value" style={{ color: medianLatency != null ? '#f59e0b' : 'var(--text-muted)' }}>
            {medianLatency != null ? `${medianLatency}ms` : '—'}
          </div>
          <div className="stat-sub">Model inference + validation + DB execution</div>
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
                  background: selectedCategory === cat ? 'var(--accent-primary)' : 'rgba(30, 41, 59, 0.7)',
                  color: selectedCategory === cat ? 'white' : 'var(--text-secondary)',
                  border: '1px solid rgba(255,255,255,0.08)'
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
                <th style={{ width: '45px' }}>Status</th>
                <th>Scenario / Question</th>
                <th>Category</th>
                <th>Expected Outcome</th>
                <th>Actual Outcome</th>
                <th>Latency</th>
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
                  const isPass = tc.result_correct;
                  const isSafety = tc.expected_behavior === 'reject';
                  const isClarify = tc.expected_behavior === 'clarification';

                  return (
                    <tr key={tc.id || idx}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {idx + 1}
                      </td>
                      <td>
                        {isPass ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--success)' }}>
                            <CheckCircle2 size={16} />
                            <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>PASS</span>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--danger)' }}>
                            <XCircle size={16} />
                            <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>FAIL</span>
                          </div>
                        )}
                      </td>
                      <td style={{ maxWidth: '420px' }}>
                        <div style={{ fontWeight: 500, color: '#f8fafc', fontSize: '0.85rem' }}>{tc.question}</div>
                        {tc.generated_sql && (
                          <div style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.72rem',
                            color: '#38bdf8',
                            marginTop: '4px',
                            background: 'rgba(0,0,0,0.25)',
                            padding: '3px 6px',
                            borderRadius: '3px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}>
                            {tc.generated_sql}
                          </div>
                        )}
                        {tc.error_message && (
                          <div style={{ fontSize: '0.72rem', color: '#fca5a5', marginTop: '3px' }}>
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
                          <span style={{ color: 'var(--warning)', fontWeight: 500 }}>Clarification</span>
                        ) : (
                          <span style={{ color: 'var(--success)', fontWeight: 500 }}>Valid Query</span>
                        )}
                      </td>
                      <td style={{ fontSize: '0.78rem' }}>
                        {tc.policy_outcome === 'rejected' ? (
                          <span style={{ color: 'var(--success)' }}>Blocked by Policy</span>
                        ) : tc.policy_outcome === 'executed' ? (
                          <span style={{ color: 'var(--success)' }}>Executed ({tc.execution_success ? 'Success' : 'Error'})</span>
                        ) : tc.policy_outcome === 'clarification' ? (
                          <span style={{ color: 'var(--warning)' }}>Clarification Requested</span>
                        ) : tc.policy_outcome === 'allowed_unsafe' ? (
                          <span style={{ color: 'var(--danger)', fontWeight: 600 }}>Not Blocked (Unsafe)</span>
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
