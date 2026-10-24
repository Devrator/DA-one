import React, { useState, useEffect } from 'react';
import { RefreshCw, CheckCircle2, AlertCircle, ArrowRight, Play, Database, Activity, Code2, Layers } from 'lucide-react';

export default function SchemaRecoveryView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchResults = async () => {
    try {
      const res = await fetch('/api/v1/schema-recovery/latest');
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (e) {
      console.warn('Could not load schema recovery results', e);
    }
  };

  useEffect(() => {
    fetchResults();
  }, []);

  const handleRunRecovery = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/schema-recovery/runs', { method: 'POST' });
      if (res.ok) {
        const interval = setInterval(async () => {
          const checkRes = await fetch('/api/v1/schema-recovery/latest');
          if (checkRes.ok) {
            const updated = await checkRes.json();
            setData(updated);
            setLoading(false);
            clearInterval(interval);
          }
        }, 5000);
      }
    } catch (e) {
      console.error('Error running schema recovery', e);
      setLoading(false);
    }
  };

  const beforeResults = data?.before_results || [];
  const afterResults = data?.after_results || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1280px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff', margin: 0 }}>
              Dynamic Schema-Change Recovery Engine
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
              Zero Retraining Required
            </span>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '4px' }}>
            Demonstrates autonomous query adaptation when target database tables (<code style={{ color: '#38bdf8' }}>product_catalog &rarr; products</code>) and columns (<code style={{ color: '#38bdf8' }}>discount_pct &rarr; discount_rate</code>) undergo controlled migrations.
          </p>
        </div>

        <button
          className="btn-primary"
          onClick={handleRunRecovery}
          disabled={loading}
          style={{ padding: '8px 20px', display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          {loading ? (
            <>
              <Activity size={16} className="animate-spin" />
              Executing Migration & Recovery...
            </>
          ) : (
            <>
              <Play size={16} fill="currentColor" />
              Execute Live Schema Recovery Test
            </>
          )}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Pre-Migration Accuracy</span>
            <CheckCircle2 size={16} style={{ color: '#10b981' }} />
          </div>
          <div className="metric-value" style={{ color: '#10b981' }}>
            {data ? `${data.accuracy_before_migration_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            Baseline accuracy on original PostgreSQL schema
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Post-Migration Accuracy</span>
            <RefreshCw size={16} style={{ color: '#38bdf8' }} />
          </div>
          <div className="metric-value" style={{ color: '#38bdf8' }}>
            {data ? `${data.accuracy_after_migration_pct}%` : '—'}
          </div>
          <div className="metric-subtext">
            Recovered accuracy without fine-tuning or retraining
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Recovered Cases</span>
            <Layers size={16} style={{ color: '#a78bfa' }} />
          </div>
          <div className="metric-value" style={{ color: '#a78bfa' }}>
            {data ? `${data.recovered_cases_count} / ${data.denominator}` : '—'}
          </div>
          <div className="metric-subtext">
            Autonomous adaptation to new schema metadata
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Retraining Burden</span>
            <Database size={16} style={{ color: '#34d399' }} />
          </div>
          <div className="metric-value" style={{ color: '#34d399' }}>
            0
          </div>
          <div className="metric-subtext">
            Zero model weights altered &bull; Live reflection
          </div>
        </div>
      </div>

      {/* Controlled Migration Actions Card */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.25rem',
      }}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc', marginBottom: '8px' }}>
          Controlled Schema Drift Applied & Safely Rolled Back
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#cbd5e1' }}>
            <span style={{ color: '#f59e0b', fontFamily: 'var(--font-mono)' }}>[DDL 1]</span>
            <code>ALTER TABLE sales.product_catalog RENAME TO products;</code>
            <ArrowRight size={13} color="#94a3b8" />
            <span style={{ color: '#38bdf8' }}>Dynamic Table Aliasing</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#cbd5e1' }}>
            <span style={{ color: '#f59e0b', fontFamily: 'var(--font-mono)' }}>[DDL 2]</span>
            <code>ALTER TABLE sales.sales_order_items RENAME COLUMN discount_pct TO discount_rate;</code>
            <ArrowRight size={13} color="#94a3b8" />
            <span style={{ color: '#38bdf8' }}>Dynamic Column Aliasing</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#cbd5e1' }}>
            <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>[CACHE]</span>
            <code>SchemaService.clear_cache() &bull; Fresh SQLAlchemy Inspection</code>
            <ArrowRight size={13} color="#94a3b8" />
            <span style={{ color: '#10b981' }}>Live Reflection Without Restart</span>
          </div>
        </div>
      </div>

      {/* Side-by-Side Comparison */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {beforeResults.map((bCase, idx) => {
          const aCase = afterResults[idx] || {};
          return (
            <div
              key={bCase.id}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '14px 16px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#94a3b8' }}>
                    {bCase.id}
                  </span>
                  <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '13px' }}>
                    {bCase.question}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{
                    fontSize: '11px',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 600,
                    background: aCase.adapted_to_new_schema ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                    color: aCase.adapted_to_new_schema ? '#34d399' : '#f87171',
                  }}>
                    {aCase.adapted_to_new_schema ? 'AUTONOMOUSLY ADAPTED' : 'ADAPTATION FAILED'}
                  </span>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                {/* Pre-Migration SQL */}
                <div style={{
                  background: 'rgba(15, 23, 42, 0.6)',
                  border: '1px solid rgba(51, 65, 85, 0.4)',
                  borderRadius: '6px',
                  padding: '10px',
                }}>
                  <div style={{ fontSize: '10px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Pre-Migration SQL (Baseline Schema)
                  </div>
                  <pre style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '11px',
                    color: '#e2e8f0',
                    margin: 0,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}>
                    {bCase.sql}
                  </pre>
                </div>

                {/* Post-Migration SQL */}
                <div style={{
                  background: 'rgba(15, 23, 42, 0.6)',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  borderRadius: '6px',
                  padding: '10px',
                }}>
                  <div style={{ fontSize: '10px', fontWeight: 600, color: '#38bdf8', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Post-Migration SQL (Recovered Live Schema)
                  </div>
                  <pre style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '11px',
                    color: '#38bdf8',
                    margin: 0,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}>
                    {aCase.sql}
                  </pre>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
