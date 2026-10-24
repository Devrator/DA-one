import React, { useState, useEffect } from 'react';
import { MessageSquare, Play, CheckCircle2, AlertCircle, Clock, Tag, ChevronDown, ChevronRight, Activity, Search, Table, Grid } from 'lucide-react';
import PageHeader from './PageHeader';

export default function ConversationsEvaluationView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedScenarios, setExpandedScenarios] = useState({});
  const [filterCategory, setFilterCategory] = useState('all');
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState('cards'); // 'cards' | 'table'

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', width: '100%', maxWidth: '1360px', margin: '0 auto' }}>
      {/* Standardized Executive Page Header */}
      <PageHeader
        icon={MessageSquare}
        title="50 Conversations Multi-Turn Benchmark"
        subtitle="Autonomous multi-turn conversational benchmark across 50 scenarios (150 total turns). Evaluates context carryover, temporal filter retention, metric pivoting, and boundary defense."
        badge={`${data?.total_scenarios || 50} Scenarios • ${data?.total_turns || 150} Turns`}
        badgeType="teal"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ display: 'flex', background: 'var(--bg-surface-subtle)', border: '1px solid var(--border-card)', borderRadius: '8px', padding: '2px' }}>
              <button 
                onClick={() => setViewMode('cards')} 
                style={{ padding: '5px 10px', border: 'none', borderRadius: '6px', cursor: 'pointer', background: viewMode === 'cards' ? 'var(--teal-primary)' : 'transparent', color: viewMode === 'cards' ? '#fff' : 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.74rem', fontWeight: 600 }}
              >
                <Grid size={13} />
                <span>Cards</span>
              </button>
              <button 
                onClick={() => setViewMode('table')} 
                style={{ padding: '5px 10px', border: 'none', borderRadius: '6px', cursor: 'pointer', background: viewMode === 'table' ? 'var(--teal-primary)' : 'transparent', color: viewMode === 'table' ? '#fff' : 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.74rem', fontWeight: 600 }}
              >
                <Table size={13} />
                <span>Table</span>
              </button>
            </div>

            <button
              className="btn-primary"
              onClick={handleRunSuite}
              disabled={loading}
              style={{ padding: '8px 18px', display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>
                  <Activity size={15} className="animate-spin" />
                  <span>Running Suite...</span>
                </>
              ) : (
                <>
                  <Play size={14} fill="currentColor" />
                  <span>Execute 50-Conversation Suite</span>
                </>
              )}
            </button>
          </div>
        }
      />

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
              color: 'var(--text-primary)',
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
                border: filterCategory === cat ? '1px solid rgba(17, 94, 89, 0.4)' : '1px solid var(--border-card)',
                background: filterCategory === cat ? 'rgba(17, 94, 89, 0.15)' : 'var(--bg-surface)',
                color: filterCategory === cat ? 'var(--teal-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              {cat === 'all' ? 'All Scenarios' : cat.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Scenario Content: Table or Cards */}
      {viewMode === 'table' ? (
        <div className="data-table-card">
          <div className="table-wrapper">
            <table className="styled-table">
              <thead>
                <tr>
                  <th style={{ width: '90px' }}>ID</th>
                  <th>Scenario Title</th>
                  <th style={{ width: '150px' }}>Category</th>
                  <th style={{ width: '130px' }}>Turn Correctness</th>
                  <th style={{ width: '130px' }}>Status</th>
                  <th style={{ width: '100px' }}>Avg Latency</th>
                  <th style={{ width: '90px', textAlign: 'center' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => {
                  const passedTurnsCount = s.turns?.filter(t => t.passed)?.length || 0;
                  const totalTurnsCount = s.turns?.length || 3;
                  const avgLat = Math.round((s.turns?.reduce((acc, t) => acc + (t.latency_ms || 200), 0) || 600) / totalTurnsCount);
                  const isExpanded = expandedScenarios[s.id];

                  return (
                    <React.Fragment key={s.id}>
                      <tr 
                        onClick={() => toggleScenario(s.id)}
                        style={{ cursor: 'pointer', background: isExpanded ? 'rgba(17, 94, 89, 0.05)' : 'transparent' }}
                      >
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--teal-primary)' }}>
                          {s.id}
                        </td>
                        <td style={{ fontWeight: 600, fontSize: '0.84rem' }}>
                          {s.title}
                        </td>
                        <td>
                          <span style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '4px', background: 'var(--bg-surface-subtle)', border: '1px solid var(--border-card)', color: 'var(--text-secondary)' }}>
                            {s.category}
                          </span>
                        </td>
                        <td style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                          {passedTurnsCount} / {totalTurnsCount} Turns
                        </td>
                        <td>
                          <span style={{
                            fontSize: '0.72rem',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontWeight: 700,
                            background: s.passed ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                            color: s.passed ? '#10b981' : '#ef4444',
                            border: `1px solid ${s.passed ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`
                          }}>
                            {s.passed ? 'PASSED' : 'PARTIAL'}
                          </span>
                        </td>
                        <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {avgLat} ms
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button 
                            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--teal-primary)' }}
                            onClick={(e) => { e.stopPropagation(); toggleScenario(s.id); }}
                          >
                            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} style={{ padding: '12px 16px', background: 'var(--bg-surface-subtle)' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              {s.turns?.map((t) => (
                                <div key={t.turn_number} style={{ padding: '8px 12px', borderRadius: '8px', background: 'var(--bg-surface)', border: '1px solid var(--border-card)' }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                      <span style={{ fontSize: '0.7rem', fontWeight: 700, padding: '1px 6px', borderRadius: '3px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                                        Turn {t.turn_number}
                                      </span>
                                      <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>{t.query}</span>
                                    </div>
                                    <span style={{ fontSize: '0.72rem', fontWeight: 700, color: t.passed ? '#10b981' : '#ef4444' }}>
                                      {t.passed ? 'PASSED' : 'FAILED'} &bull; {Math.round(t.latency_ms)}ms
                                    </span>
                                  </div>
                                  {t.sql && (
                                    <div style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: 'var(--teal-primary)', marginTop: '4px', overflowX: 'auto', background: 'var(--bg-surface-subtle)', padding: '6px 8px', borderRadius: '4px' }}>
                                      {t.sql}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Scenario Cards */
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
                    <span style={{ fontWeight: 600, color: 'var(--text-headings)', fontSize: '13px' }}>
                      {s.title}
                    </span>
                    <span style={{
                      fontSize: '10px',
                      padding: '1px 6px',
                      borderRadius: '4px',
                      background: 'var(--bg-secondary)',
                      color: 'var(--text-muted)',
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
                    background: 'rgba(251, 249, 245, 0.6)',
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
                          background: 'rgba(255, 255, 255, 0.6)',
                          border: '1px solid var(--border-card)',
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
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-headings)' }}>
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
                            color: 'var(--teal-primary)',
                            background: 'rgba(251, 249, 245, 0.9)',
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
      )}
    </div>
  );
}
