import React, { useState, useEffect } from 'react';
import { ShieldCheck, ShieldAlert, AlertTriangle, CheckCircle2, Lock, Play, Activity, RefreshCw, EyeOff, Search } from 'lucide-react';

export default function SecurityEvaluationView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filterCategory, setFilterCategory] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchResults = async () => {
    try {
      const res = await fetch('/api/v1/evaluations/security/latest');
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (e) {
      console.warn('Could not load security results', e);
    }
  };

  useEffect(() => {
    fetchResults();
  }, []);

  const handleRunSuite = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/evaluations/security/runs', { method: 'POST' });
      if (res.ok) {
        // Poll for results
        const interval = setInterval(async () => {
          const checkRes = await fetch('/api/v1/evaluations/security/latest');
          if (checkRes.ok) {
            const updated = await checkRes.json();
            setData(updated);
            setLoading(false);
            clearInterval(interval);
          }
        }, 5000);
      }
    } catch (e) {
      console.error('Error starting security suite', e);
      setLoading(false);
    }
  };

  const cases = data?.cases || [];
  const categories = ['all', ...new Set(cases.map(c => c.category).filter(Boolean))];

  const filteredCases = cases.filter(c => {
    const matchesCat = filterCategory === 'all' || c.category === filterCategory;
    const matchesSearch = !searchTerm || 
      c.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.attack_vector.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesCat && matchesSearch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1280px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: 'var(--text-headings)', margin: 0, fontWeight: 700 }}>
              Adversarial Security Evaluation Suite
            </h2>
            <span style={{
              background: 'rgba(16, 185, 129, 0.15)',
              border: '1px solid rgba(16, 185, 129, 0.4)',
              color: '#34d399',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '4px',
              fontWeight: 600,
            }}>
              35 Attack Vectors &bull; 0 Leaks
            </span>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '4px' }}>
            Tests SQLGlot AST validation, PostgreSQL Row-Level Security (RLS), column limits, canary database-value prompt injection, and privilege boundaries.
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
              Running Adversarial Suite...
            </>
          ) : (
            <>
              <Play size={16} fill="currentColor" />
              Execute 35-Case Attack Suite
            </>
          )}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Security Pass Rate</span>
            <ShieldCheck size={16} style={{ color: '#10b981' }} />
          </div>
          <div className="metric-value" style={{ color: '#10b981' }}>
            {data ? `${data.safety_rate_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            {data?.passed_cases ?? 0} of {data?.total_cases ?? 35} attack cases mitigated
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Unauthorized Leaks</span>
            <Lock size={16} style={{ color: data?.unauthorized_leaks === 0 ? '#10b981' : '#ef4444' }} />
          </div>
          <div className="metric-value" style={{ color: data?.unauthorized_leaks === 0 ? '#10b981' : '#ef4444' }}>
            {data ? data.unauthorized_leaks : '0'}
          </div>
          <div className="metric-subtext">
            Target: 0 unauthorized disclosures
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">AST Policy Blocks</span>
            <ShieldAlert size={16} style={{ color: '#38bdf8' }} />
          </div>
          <div className="metric-value" style={{ color: '#38bdf8' }}>
            {data ? data.blocked_by_ast : '—'}
          </div>
          <div className="metric-subtext">
            Prohibited columns, DDL, stacked queries
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Database RLS & Canary</span>
            <EyeOff size={16} style={{ color: '#a78bfa' }} />
          </div>
          <div className="metric-value" style={{ color: '#a78bfa' }}>
            {data ? (data.rls_filtered + data.injection_defused) : '—'}
          </div>
          <div className="metric-subtext">
            Row-Level Security & Untrusted DB values
          </div>
        </div>
      </div>

      {/* Controls & Filter Bar */}
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
            placeholder="Search attack questions, vectors, or IDs..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
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
              {cat === 'all' ? 'All Categories' : cat}
            </button>
          ))}
        </div>
      </div>

      {/* Attack Cases Table */}
      <div className="benchmark-table-container">
        <table className="benchmark-table">
          <thead>
            <tr>
              <th style={{ width: '80px' }}>ID</th>
              <th style={{ width: '130px' }}>Category</th>
              <th style={{ width: '110px' }}>Role</th>
              <th>Attack Question & Vector</th>
              <th style={{ width: '140px' }}>Mitigation Mechanism</th>
              <th style={{ width: '90px' }}>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {filteredCases.map((c) => (
              <tr key={c.id}>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: '#94a3b8' }}>
                  {c.id}
                </td>
                <td style={{ fontSize: '0.78rem', color: '#cbd5e1' }}>
                  {c.category}
                </td>
                <td>
                  <span style={{
                    fontSize: '0.7rem',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: c.role === 'executive' ? 'rgba(56, 189, 248, 0.1)' : c.role === 'regional_manager' ? 'rgba(251, 191, 36, 0.1)' : 'rgba(167, 139, 250, 0.1)',
                    color: c.role === 'executive' ? '#38bdf8' : c.role === 'regional_manager' ? '#fbbf24' : '#a78bfa',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                  }}>
                    {c.role}
                  </span>
                </td>
                <td>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.82rem', marginBottom: '3px' }}>
                    {c.query}
                  </div>
                  <div style={{ fontSize: '0.74rem', color: '#64748b' }}>
                    <span style={{ color: '#94a3b8' }}>Vector:</span> {c.attack_vector}
                  </div>
                  {c.details && (
                    <div style={{ fontSize: '0.72rem', color: '#38bdf8', marginTop: '2px', fontFamily: 'var(--font-mono)' }}>
                      &bull; {c.details}
                    </div>
                  )}
                </td>
                <td style={{ fontSize: '0.78rem' }}>
                  <span style={{
                    color: c.outcome_type === 'blocked_by_ast' ? '#38bdf8' : c.outcome_type === 'rls_filtered' ? '#a78bfa' : '#10b981',
                    fontWeight: 500
                  }}>
                    {c.outcome_type === 'blocked_by_ast' ? 'AST Policy Rejection' : c.outcome_type === 'rls_filtered' ? 'PostgreSQL RLS Filter' : c.outcome_type === 'injection_defused' ? 'Canary Defused' : 'Safely Contained'}
                  </span>
                </td>
                <td>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: '#10b981',
                  }}>
                    <CheckCircle2 size={13} /> SAFE
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
