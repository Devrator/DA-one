import React, { useState, useEffect } from 'react';
import { MessageSquare, Play, CheckCircle2, AlertCircle, Clock, Tag, ChevronDown, ChevronRight, Activity, Search } from 'lucide-react';

export default function ConversationsEvaluationView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedScenarios, setExpandedScenarios] = useState({});
  const [filterCategory, setFilterCategory] = useState('all');
  const [search, setSearch] = useState('');

  const fetchResults = async () => {
    try {
      const res = await fetch('/api/v1/evaluations/conversations/latest');
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (e) {
      console.warn('Could not load conversations results', e);
    }
  };

  useEffect(() => {
    fetchResults();
  }, []);

  const handleRunSuite = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/evaluations/conversations/runs', { method: 'POST' });
      if (res.ok) {
        const interval = setInterval(async () => {
          const checkRes = await fetch('/api/v1/evaluations/conversations/latest');
          if (checkRes.ok) {
            const updated = await checkRes.json();
            setData(updated);
            setLoading(false);
            clearInterval(interval);
          }
        }, 5000);
      }
    } catch (e) {
      console.error('Error starting conversation suite', e);
      setLoading(false);
    }
  };

  const toggleScenario = (id) => {
    setExpandedScenarios(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const scenarios = data?.scenarios || [];
  const categories = ['all', ...new Set(scenarios.map(s => s.category).filter(Boolean))];

  const filtered = scenarios.filter(s => {
    const matchesCat = filterCategory === 'all' || s.category === filterCategory;
    const matchesSearch = !search ||
      s.id.toLowerCase().includes(search.toLowerCase()) ||
      s.title.toLowerCase().includes(search.toLowerCase());
    return matchesCat && matchesSearch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1280px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: 'var(--text-headings)', margin: 0, fontWeight: 700 }}>
              50-Scenario Multi-Turn Conversation Benchmark
            </h2>
            <span style={{
              background: 'rgba(56, 189, 248, 0.15)',
              border: '1px solid rgba(56, 189, 248, 0.4)',
              color: '#38bdf8',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '4px',
              fontWeight: 600,
            }}>
              150 Total Turns &bull; 3 Turns / Scenario
            </span>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '4px' }}>
            Evaluates conversational context carryover (active metric, grouping, filters), date drilldowns, ranking comparisons, clarifying ambiguous requests, and boundary maintenance.
          </p>
        </div>

        <button
          className="btn-primary"
          onClick={handleRunSuite}
          disabled={loading}
          style={{ padding: '8px 20px', display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          {loading ? (
            <>
              <Activity size={16} className="animate-spin" />
              Running 50-Scenario Suite...
            </>
          ) : (
            <>
              <Play size={16} fill="currentColor" />
              Execute 50-Conversation Suite
            </>
          )}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Scenario Accuracy</span>
            <MessageSquare size={16} style={{ color: '#38bdf8' }} />
          </div>
          <div className="metric-value" style={{ color: '#38bdf8' }}>
            {data ? `${data.scenario_accuracy_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            {data?.fully_passed_scenarios ?? 0} of {data?.total_scenarios ?? 50} 3-turn threads passed
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Turn Correctness</span>
            <CheckCircle2 size={16} style={{ color: '#10b981' }} />
          </div>
          <div className="metric-value" style={{ color: '#10b981' }}>
            {data ? `${data.turn_accuracy_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            {data?.passed_turns ?? 0} of {data?.total_turns ?? 150} turns correct
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Clarification Rate</span>
            <AlertCircle size={16} style={{ color: '#fbbf24' }} />
          </div>
          <div className="metric-value" style={{ color: '#fbbf24' }}>
            {data ? `${data.clarification_rate_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            {data?.correct_clarifications ?? 0} of {data?.clarification_turns ?? 0} ambiguous queries clarified
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Median Turn Latency</span>
            <Clock size={16} style={{ color: '#a78bfa' }} />
          </div>
          <div className="metric-value" style={{ color: '#a78bfa' }}>
            {data ? `${data.median_latency_ms} ms` : '—'}
          </div>
          <div className="metric-subtext">
            Security boundary failures: {data?.security_failures ?? 0}
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '0.75rem 1rem',
        flexWrap: 'wrap',
        gap: '0.75rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: '240px' }}>
          <Search size={14} color="#64748b" />
          <input
            type="text"
            placeholder="Search scenarios or IDs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#f8fafc',
              fontSize: '0.85rem',
              width: '100%',
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCategory(cat)}
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 500,
                border: filterCategory === cat ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid rgba(51, 65, 85, 0.4)',
                background: filterCategory === cat ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                color: filterCategory === cat ? '#38bdf8' : '#94a3b8',
                cursor: 'pointer',
              }}
            >
              {cat === 'all' ? 'All Scenarios' : cat.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Scenario Cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {filtered.map((s) => {
          const isExpanded = expandedScenarios[s.id];
          return (
            <div
              key={s.id}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                overflow: 'hidden',
              }}
            >
              <div
                onClick={() => toggleScenario(s.id)}
                style={{
                  padding: '12px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  {isExpanded ? <ChevronDown size={15} color="#94a3b8" /> : <ChevronRight size={15} color="#94a3b8" />}
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#94a3b8' }}>
                    {s.id}
                  </span>
                  <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '13px' }}>
                    {s.title}
                  </span>
                  <span style={{
                    fontSize: '10px',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: 'rgba(51, 65, 85, 0.4)',
                    color: '#94a3b8',
                  }}>
                    {s.category}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{
                    fontSize: '11px',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 600,
                    background: s.passed ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                    color: s.passed ? '#34d399' : '#f87171',
                  }}>
                    {s.passed ? '3/3 TURNS PASSED' : 'PARTIAL / FAILED'}
                  </span>
                </div>
              </div>

              {isExpanded && (
                <div style={{
                  padding: '12px 16px',
                  background: 'rgba(15, 23, 42, 0.4)',
                  borderTop: '1px solid var(--border-subtle)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}>
                  {s.turns.map((t) => (
                    <div
                      key={t.turn_number}
                      style={{
                        padding: '10px 12px',
                        background: 'rgba(30, 41, 59, 0.4)',
                        border: '1px solid rgba(51, 65, 85, 0.3)',
                        borderRadius: '6px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            fontSize: '10px',
                            fontWeight: 700,
                            padding: '1px 6px',
                            borderRadius: '3px',
                            background: 'rgba(56, 189, 248, 0.15)',
                            color: '#38bdf8',
                          }}>
                            Turn {t.turn_number}
                          </span>
                          <span style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>
                            {t.query}
                          </span>
                        </div>
                        <span style={{
                          fontSize: '10px',
                          color: t.passed ? '#10b981' : '#f87171',
                          fontWeight: 600,
                        }}>
                          {t.passed ? 'PASSED' : 'FAILED'} &bull; {Math.round(t.latency_ms)}ms
                        </span>
                      </div>
                      {t.sql && (
                        <div style={{
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                          color: '#38bdf8',
                          background: 'rgba(15, 23, 42, 0.6)',
                          padding: '6px 8px',
                          borderRadius: '4px',
                          marginTop: '4px',
                          overflowX: 'auto',
                        }}>
                          {t.sql}
                        </div>
                      )}
                      {t.fail_reason && (
                        <div style={{ fontSize: '11px', color: '#f87171', marginTop: '3px' }}>
                          Error: {t.fail_reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
