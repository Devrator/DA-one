import React, { useState, useEffect, useCallback } from 'react';
import {
  Sparkles, Play, Activity, TrendingUp, TrendingDown, AlertTriangle, Target,
  Lightbulb, ShieldAlert, ChevronDown, ChevronUp, Search, Compass, X, Bookmark,
  ArrowRight, RefreshCw, Network, SlidersHorizontal,
} from 'lucide-react';
import PageHeader from './PageHeader';

const SEV_META = {
  critical: { label: 'Critical', color: '#ef4444', icon: ShieldAlert },
  warning: { label: 'Warning', color: '#f59e0b', icon: AlertTriangle },
  watch: { label: 'Watch', color: '#38bdf8', icon: Activity },
  info: { label: 'Info', color: '#64748b', icon: Compass },
};

const TYPE_META = {
  trend: { label: 'Trend', icon: TrendingUp },
  anomaly: { label: 'Anomaly', icon: AlertTriangle },
  concentration: { label: 'Concentration', icon: Target },
  underperformer: { label: 'Under-performer', icon: TrendingDown },
  opportunity: { label: 'Opportunity', icon: Lightbulb },
};

const fmtMoney = (n) => {
  const v = Number(n || 0);
  if (Math.abs(v) >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
  if (Math.abs(v) >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
  return '$' + v.toLocaleString('en-US', { maximumFractionDigits: 2 });
};
const fmtNum = (n) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });

// ---- Inline mini charts (no external charting dependency) ----
function MiniLineChart({ data }) {
  const values = data.map((d) => Number(d.value ?? d.value_per_order ?? 0));
  if (values.length < 2) return null;
  const w = 320, h = 90, pad = 8;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  const pts = values.map((v, i) => `${pad + i * step},${h - pad - ((v - min) / span) * (h - pad * 2)}`);
  const area = `${pad},${h - pad} ${pts.join(' ')} ${pad + (values.length - 1) * step},${h - pad}`;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="discLine" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(20,184,166,0.35)" />
          <stop offset="100%" stopColor="rgba(20,184,166,0)" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#discLine)" />
      <polyline points={pts.join(' ')} fill="none" stroke="#14b8a6" strokeWidth="2" />
      {pts.map((p, i) => {
        const [x, y] = p.split(',');
        return <circle key={i} cx={x} cy={y} r="2.5" fill="#115e59" />;
      })}
    </svg>
  );
}

function MiniBarChart({ data }) {
  const rows = data.slice(0, 8);
  const values = rows.map((d) => Number(d.value ?? d.value_per_order ?? d.revenue ?? 0));
  if (!values.length) return null;
  const max = Math.max(...values) || 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', width: '100%' }}>
      {rows.map((d, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', width: '86px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(d.segment ?? d.period ?? '')}>
            {String(d.segment ?? d.period ?? '')}
          </span>
          <div style={{ flex: 1, background: 'rgba(17,94,89,0.08)', borderRadius: '4px', height: '14px', position: 'relative' }}>
            <div style={{ width: `${(values[i] / max) * 100}%`, height: '100%', borderRadius: '4px', background: 'linear-gradient(90deg,#115e59,#2dd4bf)' }} />
          </div>
          <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', width: '62px', textAlign: 'right' }}>{fmtMoney(values[i])}</span>
        </div>
      ))}
    </div>
  );
}

function InsightCard({ finding, onExplore, onDismiss, onSave, onInvestigate, onSimulate }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV_META[finding.severity] || SEV_META.info;
  const type = TYPE_META[finding.finding_type] || TYPE_META.trend;
  const SevIcon = sev.icon;
  const TypeIcon = type.icon;
  const chart = finding.chart_spec?.type === 'line' ? MiniLineChart : MiniBarChart;
  const supporting = Array.isArray(finding.supporting_data) ? finding.supporting_data : [];
  const delta = Number(finding.delta_pct || 0);
  const isMoney = finding.metric_name && /revenue|amount|price/i.test(finding.metric_name);
  const fmtVal = isMoney ? fmtMoney : fmtNum;

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-card)',
      borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)', overflow: 'hidden',
    }}>
      <div style={{ height: '4px', background: sev.color }} />
      <div style={{ padding: '1rem 1.15rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.66rem', fontWeight: 700, padding: '3px 8px', borderRadius: '999px', background: `${sev.color}1a`, color: sev.color, border: `1px solid ${sev.color}40`, textTransform: 'uppercase', letterSpacing: '0.03em' }}>
              <SevIcon size={12} /> {sev.label}
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              <TypeIcon size={13} /> {type.label}
            </span>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: delta >= 0 ? '#10b981' : '#ef4444', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
              {delta >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
              {delta >= 0 ? '+' : ''}{delta.toFixed(1)}%
            </div>
            <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)' }}>{finding.period_label || ''}</div>
          </div>
        </div>

        <h3 style={{ margin: '10px 0 6px', fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)', lineHeight: 1.35 }}>
          {finding.title}
        </h3>
        <p style={{ margin: 0, fontSize: '0.83rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {finding.narrative}
        </p>

        {supporting.length >= 2 && (
          <div style={{ marginTop: '12px', padding: '10px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)' }}>
            {React.createElement(chart, { data: supporting })}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginTop: '12px', flexWrap: 'wrap' }}>
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Baseline</span> {fmtVal(finding.baseline_value)}
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Current</span> {fmtVal(finding.current_value)}
          </div>
          {finding.data_freshness_at && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <RefreshCw size={11} /> {new Date(finding.data_freshness_at).toLocaleString()}
            </div>
          )}
        </div>

        <button onClick={() => setExpanded((v) => !v)} style={{ marginTop: '10px', background: 'none', border: 'none', color: 'var(--teal-primary)', fontSize: '0.76rem', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', padding: 0 }}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {expanded ? 'Hide evidence' : 'Show evidence & reasoning'}
        </button>

        {expanded && (
          <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <EvidenceBlock title="Why it might matter (hypothesis — not a causal claim)" tone="hypothesis">
              {finding.hypothesis}
            </EvidenceBlock>
            <EvidenceBlock title="Suggested next steps" tone="steps">
              {finding.suggested_next_steps}
            </EvidenceBlock>
            <EvidenceBlock title="Evidence & calculation" tone="meta">
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', fontSize: '0.74rem', lineHeight: 1.5 }}>
                <span style={{ color: 'var(--text-muted)' }}>Metric</span><span>{finding.metric_name}</span>
                <span style={{ color: 'var(--text-muted)' }}>Dimension</span><span>{finding.dimension_name}{finding.segment ? ` — ${finding.segment}` : ''}</span>
                <span style={{ color: 'var(--text-muted)' }}>Comparison</span><span>{finding.comparison_label}</span>
                <span style={{ color: 'var(--text-muted)' }}>Tables</span><span style={{ fontFamily: 'var(--font-mono)' }}>{(finding.source_tables || []).join(', ')}</span>
                <span style={{ color: 'var(--text-muted)' }}>Filter</span><span style={{ fontFamily: 'var(--font-mono)' }}>{finding.calculation?.filters || 'none'}</span>
                <span style={{ color: 'var(--text-muted)' }}>Calculation</span><span style={{ fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>{finding.calculation?.measure_expr}</span>
              </div>
            </EvidenceBlock>
            <EvidenceBlock title="Assumptions" tone="meta">
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {(finding.assumptions || []).map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </EvidenceBlock>
            <EvidenceBlock title="Limitations" tone="meta">
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {(finding.limitations || []).map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            </EvidenceBlock>
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
          <button onClick={() => onInvestigate && onInvestigate(finding.id)} className="btn-primary" style={{ padding: '7px 14px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem' }}>
            <Network size={14} /> Open Investigation
          </button>
          <button onClick={() => onSimulate && onSimulate(finding.id)} style={{ padding: '7px 14px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', background: 'var(--bg-surface)', color: 'var(--copper-primary, #c27847)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
            <SlidersHorizontal size={14} /> Simulate What-If
          </button>
          <button onClick={() => onExplore(finding.explore_question || finding.title)} style={{ padding: '7px 14px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', background: 'var(--bg-surface)', color: 'var(--teal-primary)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
            Explore Further <ArrowRight size={14} />
          </button>
          <button onClick={() => onSave(finding.id)} style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', background: finding.status === 'saved' ? 'rgba(17,94,89,0.12)' : 'var(--bg-surface)', color: 'var(--teal-primary)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
            <Bookmark size={13} /> {finding.status === 'saved' ? 'Saved' : 'Save'}
          </button>
          <button onClick={() => onDismiss(finding.id)} style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', background: 'var(--bg-surface)', color: 'var(--text-muted)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
            <X size={13} /> Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}

function EvidenceBlock({ title, tone, children }) {
  const bg = tone === 'hypothesis' ? 'rgba(56,189,248,0.07)' : tone === 'steps' ? 'rgba(17,94,89,0.06)' : 'var(--bg-secondary)';
  const border = tone === 'hypothesis' ? 'rgba(56,189,248,0.25)' : tone === 'steps' ? 'rgba(17,94,89,0.2)' : 'var(--border-subtle)';
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 'var(--radius-md)', padding: '10px 12px' }}>
      <div style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-muted)', marginBottom: '6px' }}>{title}</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{children}</div>
    </div>
  );
}

export default function DiscoverView({ onExploreFurther, onOpenInvestigation, onSimulate }) {
  const [findings, setFindings] = useState([]);
  const [summary, setSummary] = useState({ critical: 0, warning: 0, watch: 0, info: 0 });
  const [runInfo, setRunInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');

  const fetchFindings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/discover/findings?status=active&limit=100');
      if (res.ok) {
        const json = await res.json();
        setFindings(json.findings || []);
        setSummary(json.summary || summary);
      }
    } catch (e) {
      console.warn('Could not load discovery findings', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const pollRun = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/discover/runs/latest');
      if (res.ok) {
        const json = await res.json();
        setRunInfo(json);
        if (json.in_memory?.status === 'running' || json.run?.status === 'running') {
          return true; // still running
        }
        return false;
      }
    } catch (e) { /* ignore */ }
    return false;
  }, []);

  useEffect(() => {
    fetchFindings();
    pollRun();
  }, [fetchFindings, pollRun]);

  const handleRun = async () => {
    setStarting(true);
    try {
      await fetch('/api/v1/discover/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      let running = true;
      let tries = 0;
      while (running && tries < 40) {
        await new Promise((r) => setTimeout(r, 2000));
        running = await pollRun();
        tries += 1;
      }
      await fetchFindings();
    } catch (e) {
      console.error('Discovery run failed', e);
    } finally {
      setStarting(false);
    }
  };

  const handleDismiss = async (id) => {
    await fetch(`/api/v1/discover/findings/${id}/dismiss`, { method: 'POST' });
    setFindings((prev) => prev.filter((f) => f.id !== id));
  };
  const handleSave = async (id) => {
    await fetch(`/api/v1/discover/findings/${id}/save`, { method: 'POST' });
    setFindings((prev) => prev.map((f) => f.id === id ? { ...f, status: 'saved' } : f));
  };

  const visible = findings.filter((f) => {
    const matchesFilter = filter === 'all' || f.severity === filter || f.finding_type === filter;
    const matchesSearch = !search || (f.title || '').toLowerCase().includes(search.toLowerCase())
      || (f.segment || '').toLowerCase().includes(search.toLowerCase())
      || (f.metric_name || '').toLowerCase().includes(search.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const totalNew = runInfo?.run?.findings_new ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', width: '100%', maxWidth: '1360px', margin: '0 auto' }}>
      <PageHeader
        icon={Sparkles}
        title="Discover & Early Warnings"
        subtitle="QueryPilot proactively analyzes your authorized, live data and surfaces meaningful changes, trends, concentration risks and opportunities before you ask."
        badge={starting ? 'Analyzing live data…' : `${findings.length} live findings`}
        badgeType={summary.critical > 0 ? 'amber' : 'teal'}
        actions={
          <button className="btn-primary" onClick={handleRun} disabled={starting || loading} style={{ padding: '8px 18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            {starting || loading ? (<><Activity size={15} className="animate-spin" /><span>Analyzing…</span></>) : (<><Play size={14} fill="currentColor" /><span>Run Discovery</span></>)}
          </button>
        }
      />

      {runInfo?.run && (
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '0.7rem 1rem', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--teal-primary)' }}>Last run:</strong> {runInfo.run.status} · {runInfo.run.trigger}</span>
          <span>Schema: <strong>{runInfo.run.schema_name}</strong></span>
          <span>Metrics analyzed: <strong>{runInfo.run.metrics_analyzed}</strong></span>
          <span>Dimensions: <strong>{runInfo.run.dimensions_analyzed}</strong></span>
          <span>New findings: <strong>{totalNew}</strong> · Deduped: <strong>{runInfo.run.findings_deduped}</strong></span>
          <span>Duration: <strong>{((runInfo.run.duration_ms || 0) / 1000).toFixed(1)}s</strong></span>
          {runInfo.run.detail?.profile?.time_column && (
            <span style={{ color: 'var(--text-muted)' }}>Fact: {runInfo.run.detail.profile.fact_table} · Time: {runInfo.run.detail.profile.time_column}</span>
          )}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '0.75rem 1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: '220px' }}>
          <Search size={14} color="#64748b" />
          <input type="text" placeholder="Search findings, segments, metrics…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: '0.85rem', width: '100%' }} />
        </div>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {['all', 'critical', 'warning', 'watch', 'trend', 'concentration', 'underperformer', 'opportunity'].map((k) => (
            <button key={k} onClick={() => setFilter(k)} style={{ padding: '4px 10px', borderRadius: '6px', fontSize: '11px', fontWeight: 500, textTransform: 'capitalize', border: filter === k ? '1px solid rgba(17,94,89,0.4)' : '1px solid var(--border-card)', background: filter === k ? 'rgba(17,94,89,0.15)' : 'var(--bg-surface)', color: filter === k ? 'var(--teal-primary)' : 'var(--text-secondary)', cursor: 'pointer' }}>
              {k}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '3.5rem 1rem', background: 'var(--bg-surface)', border: '1px dashed var(--border-card)', borderRadius: 'var(--radius-lg)' }}>
          <Compass size={40} color="var(--text-muted)" style={{ marginBottom: '12px' }} />
          <h3 style={{ margin: '0 0 6px', color: 'var(--text-headings)', fontSize: '1.05rem' }}>
            {findings.length === 0 ? 'No meaningful findings yet' : 'No findings match your filters'}
          </h3>
          <p style={{ margin: '0 auto', maxWidth: '460px', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>
            {findings.length === 0
              ? 'Discovery only surfaces statistically significant, material changes. If your data is currently stable within thresholds, an empty feed is the correct, honest result. Run discovery to re-scan the live database.'
              : 'Try a different severity or clear the search to see all active findings.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '1rem' }}>
          {visible.map((f) => (
            <InsightCard key={f.id} finding={f} onExplore={onExploreFurther} onDismiss={handleDismiss} onSave={handleSave} onInvestigate={onOpenInvestigation} onSimulate={onSimulate} />
          ))}
        </div>
      )}
    </div>
  );
}
