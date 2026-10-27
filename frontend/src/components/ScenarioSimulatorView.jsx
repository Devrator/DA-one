import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  SlidersHorizontal, Play, Save, Copy, Trash2, GitCompareArrows, RefreshCw,
  Loader2, AlertTriangle, ShieldCheck, TrendingUp, TrendingDown, Network, X, Database,
} from 'lucide-react';
import PageHeader from './PageHeader';

const fmtVal = (n) => {
  const v = Number(n || 0);
  if (Math.abs(v) >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
  if (Math.abs(v) >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
  return v.toLocaleString('en-US', { maximumFractionDigits: v % 1 === 0 ? 0 : 2 });
};

function Badge({ kind }) {
  const map = {
    observed: { label: 'OBSERVED DATA', color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
    assumption: { label: 'YOUR ASSUMPTION', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
    calculated: { label: 'CALCULATED SCENARIO', color: 'var(--teal-primary)', bg: 'rgba(20,184,166,0.12)' },
  };
  const m = map[kind] || map.calculated;
  return (
    <span style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.04em', color: m.color,
      background: m.bg, border: `1px solid ${m.color}44`, borderRadius: '6px', padding: '2px 7px' }}>
      {m.label}
    </span>
  );
}

function DeltaCard({ label, m, unit }) {
  if (!m) return null;
  const up = (m.delta_abs || 0) >= 0;
  const Arrow = up ? TrendingUp : TrendingDown;
  return (
    <div className="da-stat-card" style={{ padding: '14px 16px', borderRadius: '12px',
      background: 'var(--bg-surface)', border: '1px solid var(--border-card)' }}>
      <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '6px' }}>{label}</div>
      <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text-primary)' }}>
        {unit === 'money' ? fmtVal(m.scenario) : Number(m.scenario).toLocaleString('en-US', { maximumFractionDigits: 0 })}
      </div>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
        baseline {unit === 'money' ? fmtVal(m.baseline) : Number(m.baseline).toLocaleString('en-US', { maximumFractionDigits: 0 })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginTop: '8px',
        color: up ? '#10b981' : '#dc2626', fontWeight: 700, fontSize: '0.82rem' }}>
        <Arrow size={15} />
        {up ? '+' : ''}{Number(m.delta_pct).toFixed(1)}%
        <span style={{ color: 'var(--text-tertiary)', fontWeight: 500 }}>
          ({up ? '+' : ''}{unit === 'money' ? fmtVal(m.delta_abs) : Number(m.delta_abs).toFixed(0)})
        </span>
      </div>
    </div>
  );
}

function LeverSlider({ lever, value, onChange }) {
  const v = Number(value || 0);
  return (
    <div style={{ marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
        <label style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>{lever.label}</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="number" min={lever.min} max={lever.max} step={lever.step} value={v}
            onChange={(e) => onChange(lever.key, e.target.value)}
            style={{ width: '78px', padding: '4px 6px', borderRadius: '7px', fontSize: '0.8rem',
              border: '1px solid var(--border-card)', background: 'var(--bg-input, var(--bg-surface))', color: 'var(--text-primary)' }} />
          <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', minWidth: '92px' }}>{lever.unit}</span>
        </div>
      </div>
      <input
        type="range" min={lever.min} max={lever.max} step={lever.step} value={v}
        onChange={(e) => onChange(lever.key, e.target.value)}
        style={{ width: '100%', accentColor: 'var(--teal-primary)' }} />
      <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>{lever.help}</div>
    </div>
  );
}

export default function ScenarioSimulatorView({ currentRole, focusFindingId, onOpenInvestigation }) {
  const [caps, setCaps] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [assumptions, setAssumptions] = useState({});
  const [results, setResults] = useState(null);
  const [scenarioName, setScenarioName] = useState('Base case');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState([]);
  const [compareSel, setCompareSel] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [showEvidence, setShowEvidence] = useState(false);

  const loadSaved = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/scenarios');
      if (r.ok) setSaved((await r.json()).scenarios || []);
    } catch (e) { /* ignore */ }
  }, []);

  // Load capabilities + baseline once per role (schema-adaptive: only real levers).
  const initScenario = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const cr = await fetch(`/api/v1/scenarios/capabilities?role=${encodeURIComponent(currentRole)}`);
      const capsData = await cr.json();
      setCaps(capsData);
      if (!capsData.can_simulate) {
        setBaseline(null);
        setError(capsData.unavailable_reasons?.[0] || 'The connected schema does not expose the metrics needed to build a baseline.');
        return;
      }
      const br = await fetch('/api/v1/scenarios/baseline', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ role: currentRole }),
      });
      const bres = await br.json();
      if (bres.ok) { setBaseline(bres.baseline); setAssumptions({}); }
      else setError(bres.reason || 'Could not build a baseline from the connected data.');
    } catch (e) {
      setError('Failed to initialise simulator: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [currentRole]);

  useEffect(() => { initScenario(); loadSaved(); }, [initScenario, loadSaved]);

  // Deterministic recompute (debounced) whenever assumptions change.
  useEffect(() => {
    if (!baseline) { setResults(null); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch('/api/v1/scenarios/simulate', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
          body: JSON.stringify({ role: currentRole, baseline, assumptions, name: scenarioName }),
        });
        if (r.ok) setResults(await r.json());
        else { const e = await r.json(); setError(Array.isArray(e.detail) ? e.detail.join('; ') : (e.detail?.errors || 'Simulation rejected.').toString()); }
      } catch (e) { /* ignore transient */ }
    }, 260);
    return () => clearTimeout(t);
  }, [baseline, assumptions, scenarioName, currentRole]);

  const onLever = (key, raw) => {
    const v = raw === '' ? 0 : Number(raw);
    setAssumptions((prev) => ({ ...prev, [key]: Number.isNaN(v) ? 0 : v }));
  };

  const saveScenario = async () => {
    if (!baseline) return;
    setLoading(true);
    try {
      const r = await fetch('/api/v1/scenarios', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ name: scenarioName, role: currentRole, baseline, assumptions, source: focusFindingId ? 'finding' : 'manual', finding_id: focusFindingId || null }),
      });
      if (r.ok) { const s = await r.json(); await loadSaved(); setSaved((prev) => prev.some((x) => x.id === s.id) ? prev : [s, ...prev]); }
      else setError('Save rejected: ' + (await r.text()));
    } catch (e) { setError('Save failed: ' + e.message); }
    finally { setLoading(false); }
  };

  const duplicate = async (id) => { await fetch(`/api/v1/scenarios/${id}/duplicate`, { method: 'POST' }); loadSaved(); };
  const remove = async (id) => { await fetch(`/api/v1/scenarios/${id}`, { method: 'DELETE' }); setCompareSel((p) => p.filter((x) => x !== id)); loadSaved(); };
  const toggleCompare = (id) => setCompareSel((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2));

  const runCompare = async () => {
    if (compareSel.length < 2) return;
    const r = await fetch('/api/v1/scenarios/compare', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario_ids: compareSel }),
    });
    if (r.ok) setComparison(await r.json());
  };

  const loadScenario = async (id) => {
    const r = await fetch(`/api/v1/scenarios/${id}`);
    if (!r.ok) return;
    const s = await r.json();
    if (s.baseline && Object.keys(s.baseline).length) setBaseline(s.baseline);
    setAssumptions(s.assumptions || {});
    setScenarioName(s.name || 'Loaded scenario');
  };

  const sendToInvestigation = async () => {
    if (!baseline || !results) { setError('Build a baseline before sending a scenario to an investigation.'); return; }
    setLoading(true);
    try {
      // 1) persist the current scenario so it has a stable id + stored assumptions
      const sr = await fetch('/api/v1/scenarios', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ name: scenarioName, role: currentRole, baseline, assumptions, source: focusFindingId ? 'finding' : 'manual', finding_id: focusFindingId || null }),
      });
      if (!sr.ok) { setError('Could not persist scenario.'); return; }
      const s = await sr.json();

      // 2) open (or reuse) an investigation and send the scenario into a branch
      const net = results.metrics?.net_revenue || {};
      const rootQ = `Investigate what-if scenario "${scenarioName}": projected net revenue ${fmtVal(net.scenario)} (${(net.delta_pct || 0).toFixed(1)}% vs observed baseline ${fmtVal(net.baseline)}). Validate the assumptions against real per-segment data.`;
      const ir = await fetch('/api/v1/investigations', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ finding_id: focusFindingId || null, role: currentRole, title: `Scenario: ${scenarioName}`, root_question: rootQ, run_root_cause: false }),
      });
      if (!ir.ok) { setError('Could not create investigation.'); return; }
      const inv = await ir.json();
      const send = await fetch(`/api/v1/scenarios/${s.id}/send-to-investigation`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ investigation_id: inv.id }),
      });
      await loadSaved();
      if (send.ok && onOpenInvestigation) onOpenInvestigation(inv.id);
      else setError('Investigation created, but scenario link failed.');
    } catch (e) { setError('Send to investigation failed: ' + e.message); }
    finally { setLoading(false); }
  };

  const availableLevers = useMemo(() => (caps?.levers || []).filter((l) => l.available), [caps]);
  const net = results?.metrics?.net_revenue;
  const margin = results?.metrics?.contribution_margin;

  return (
    <div>
      <PageHeader
        icon={SlidersHorizontal}
        title="What-If Decision Simulator"
        subtitle="Build a scenario from real data, adjust assumptions, and see deterministically recalculated outcomes — never a guessed forecast."
        badge={baseline ? 'Real baseline loaded' : 'Loading'}
        badgeType={baseline ? 'success' : 'info'}
        actions={
          <button className="da-btn-secondary" onClick={initScenario} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <RefreshCw size={15} /> Rebuild baseline
          </button>
        }
      />

      {error && (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', background: 'rgba(220,38,38,0.08)',
          border: '1px solid rgba(220,38,38,0.28)', color: '#dc2626', borderRadius: '10px', padding: '10px 14px', margin: '0 0 16px', fontSize: '0.82rem' }}>
          <AlertTriangle size={16} /> {error}
          <X size={15} style={{ marginLeft: 'auto', cursor: 'pointer' }} onClick={() => setError(null)} />
        </div>
      )}

      {loading && !baseline && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-secondary)', padding: '24px' }}>
          <Loader2 className="animate-spin" size={18} /> Reading authorized schema…
        </div>
      )}

      {baseline && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(340px, 1fr) minmax(420px, 1.4fr)', gap: '18px', alignItems: 'start' }}>
          {/* LEFT: assumptions */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '14px', padding: '18px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
              <h3 style={{ margin: 0, fontSize: '0.98rem', color: 'var(--text-primary)' }}>Assumptions</h3>
              <Badge kind="assumption" />
            </div>
            <p style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', margin: '0 0 14px' }}>
              Only metrics present in the connected schema appear here. Setting all to 0 reproduces the observed baseline exactly.
            </p>

            {availableLevers.map((l) => (
              <LeverSlider key={l.key} lever={l} value={assumptions[l.key] || 0} onChange={onLever} />
            ))}

            {(caps?.levers || []).filter((l) => !l.available).map((l) => (
              <div key={l.key} style={{ marginBottom: '14px', opacity: 0.55 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  <span>{l.label}</span><span style={{ fontSize: '0.68rem', color: '#dc2626' }}>unavailable</span>
                </div>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>{l.help} — the schema has no column for this metric, so it is not invented.</div>
              </div>
            ))}

            <div style={{ borderTop: '1px solid var(--border-card)', paddingTop: '12px', marginTop: '6px' }}>
              <input value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} placeholder="Scenario name"
                style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--border-card)',
                  background: 'var(--bg-input, var(--bg-surface))', color: 'var(--text-primary)', marginBottom: '10px', fontSize: '0.85rem' }} />
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button className="btn-primary" onClick={saveScenario} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px', fontSize: '0.82rem' }}>
                  <Save size={14} /> Save
                </button>
                <button onClick={() => setAssumptions({})} style={{ padding: '8px 14px', fontSize: '0.82rem', background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
                  Reset to 0
                </button>
                <button onClick={sendToInvestigation} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px', fontSize: '0.82rem', background: 'var(--bg-surface)', color: 'var(--teal-primary)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
                  <Network size={14} /> Send to Investigation
                </button>
              </div>
            </div>
          </div>

          {/* RIGHT: outcome */}
          <div>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '14px', padding: '18px', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                <h3 style={{ margin: 0, fontSize: '0.98rem', color: 'var(--text-primary)' }}>Calculated outcome</h3>
                <Badge kind="calculated" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
                <DeltaCard label="Net revenue" m={net} unit="money" />
                <DeltaCard label="Gross revenue" m={results?.metrics?.gross_revenue} unit="money" />
                <DeltaCard label="Contribution margin" m={margin} unit="money" />
                <DeltaCard label="Units" m={results?.metrics?.units} unit="count" />
              </div>
              {results?.computed_at && (
                <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', marginTop: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <ShieldCheck size={13} /> Calculated {new Date(results.computed_at).toLocaleString()} · read-only under {currentRole} RLS · arithmetic, not a forecast.
                </div>
              )}
              {results?.limitations?.length > 0 && (
                <ul style={{ margin: '10px 0 0', paddingLeft: '18px', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                  {results.limitations.map((l, i) => <li key={i}>{l}</li>)}
                </ul>
              )}
            </div>

            {/* observed baseline + evidence + formulas */}
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '14px', padding: '18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <h3 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Database size={16} /> Observed baseline & formulas
                </h3>
                <button onClick={() => setShowEvidence((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--teal-primary)', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}>
                  {showEvidence ? 'Hide' : 'Show'} details
                </button>
              </div>
              <div style={{ display: 'flex', gap: '8px', margin: '8px 0' }}>
                <Badge kind="observed" />
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                Metric: <b>{baseline.source_metric?.label}</b> · Period: <b>{baseline.period_label}</b> · Units: <b>{Number(baseline.units).toLocaleString()}</b> ·
                Avg unit price: <b>{fmtVal(baseline.avg_unit_price)}</b> · Realized factor: <b>{Number(baseline.realized_factor).toFixed(3)}</b>
                {baseline.unit_cost != null && <> · Unit cost: <b>{fmtVal(baseline.unit_cost)}</b></>}
              </div>
              {showEvidence && (
                <div style={{ marginTop: '12px', borderTop: '1px solid var(--border-card)', paddingTop: '12px' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                    Source tables: {(baseline.source_tables || []).join(', ')} · Filters: {baseline.status_filter || 'none'}
                  </div>
                  <pre style={{ background: 'var(--bg-input, #0b0f14)', color: '#d7e0ea', borderRadius: '8px', padding: '10px', fontSize: '0.68rem', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                    {baseline.evidence_sql}
                  </pre>
                  {results?.formulas && (
                    <div style={{ marginTop: '10px' }}>
                      <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>Formulas</div>
                      {Object.entries(results.formulas).map(([k, v]) => (
                        <div key={k} style={{ fontFamily: 'monospace', fontSize: '0.68rem', color: 'var(--text-secondary)' }}>{v}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* saved scenarios + compare */}
      <div style={{ marginTop: '22px', background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '14px', padding: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Saved scenarios</h3>
          <button className="da-btn-secondary" onClick={runCompare} disabled={compareSel.length < 2}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', opacity: compareSel.length < 2 ? 0.5 : 1 }}>
            <GitCompareArrows size={15} /> Compare selected ({compareSel.length})
          </button>
        </div>
        {saved.length === 0 && <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>No saved scenarios yet. Adjust assumptions and press Save.</p>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '12px' }}>
          {saved.map((s) => (
            <div key={s.id} style={{ border: '1px solid var(--border-card)', borderRadius: '10px', padding: '12px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.86rem', color: 'var(--text-primary)' }}>{s.name}</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', margin: '4px 0 8px' }}>
                {s.metric_label || '—'} · {s.period_label || 'all'} · {s.status}
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button onClick={() => loadScenario(s.id)} style={miniBtn}>Load</button>
                <button onClick={() => toggleCompare(s.id)} style={{ ...miniBtn, color: compareSel.includes(s.id) ? 'var(--teal-primary)' : 'var(--text-secondary)', borderColor: compareSel.includes(s.id) ? 'var(--teal-primary)' : 'var(--border-card)' }}>Compare</button>
                <button onClick={() => duplicate(s.id)} style={miniBtn} title="Duplicate"><Copy size={13} /></button>
                <button onClick={() => remove(s.id)} style={{ ...miniBtn, color: '#dc2626' }} title="Delete"><Trash2 size={13} /></button>
              </div>
            </div>
          ))}
        </div>

        {comparison && (
          <div style={{ marginTop: '16px', borderTop: '1px solid var(--border-card)', paddingTop: '14px', overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '6px' }}>Scenario</th><th>Net revenue</th><th>Δ%</th><th>Margin</th><th>Assumptions</th>
                </tr>
              </thead>
              <tbody>
                {comparison.scenarios.map((c) => (
                  <tr key={c.id} style={{ borderTop: '1px solid var(--border-card)' }}>
                    <td style={{ padding: '6px', fontWeight: 600 }}>{c.name}</td>
                    <td>{fmtVal(c.net_revenue?.scenario)}</td>
                    <td style={{ color: (c.net_revenue?.delta_abs || 0) >= 0 ? '#10b981' : '#dc2626' }}>
                      {(c.net_revenue?.delta_pct || 0) >= 0 ? '+' : ''}{(c.net_revenue?.delta_pct || 0).toFixed(1)}%
                    </td>
                    <td>{c.contribution_margin ? fmtVal(c.contribution_margin.scenario) : 'n/a'}</td>
                    <td style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{Object.entries(c.assumptions || {}).map(([k, v]) => `${k}=${v}`).join(', ') || 'none'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const miniBtn = { padding: '5px 10px', fontSize: '0.72rem', background: 'var(--bg-input, var(--bg-surface))',
  color: 'var(--text-secondary)', border: '1px solid var(--border-card)', borderRadius: '7px', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', gap: '4px' };
