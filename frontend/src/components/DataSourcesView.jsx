import React, { useState, useEffect, useCallback } from 'react';
import {
  Database, Server, RefreshCw, Loader2, AlertTriangle, CheckCircle2, XCircle,
  Network, Link2, Trash2, Play, ChevronDown, ChevronUp, ShieldCheck, GitBranch, Layers,
  PlugZap, Eye, Ban, ArrowRight, Boxes,
} from 'lucide-react';
import PageHeader from './PageHeader';
import SapConnectorPanel from './SapConnectorPanel';

const joinTypes = ['inner', 'left', 'right', 'full'];

const smallBtn = {
  display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '5px 11px',
  fontSize: '0.76rem', borderRadius: '8px', cursor: 'pointer', border: '1px solid var(--border-card)',
  background: 'var(--bg-surface)', color: 'var(--teal-primary)',
};
const chip = (active) => ({
  padding: '4px 12px', fontSize: '0.76rem', borderRadius: '14px', cursor: 'pointer',
  border: `1px solid ${active ? 'var(--teal-primary)' : 'var(--border-card)'}`,
  background: active ? 'rgba(20,184,166,0.12)' : 'transparent',
  color: active ? 'var(--teal-primary)' : 'var(--text-secondary)',
});

function HealthDot({ ok }) {
  return ok
    ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color: '#10b981', fontSize: '0.74rem' }}><CheckCircle2 size={14} /> Healthy</span>
    : <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color: '#dc2626', fontSize: '0.74rem' }}><XCircle size={14} /> Unreachable</span>;
}

function SourceCard({ source, catalog, expanded, onToggle, loadingCatalog }) {
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '12px', padding: '14px 16px', marginBottom: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div style={{ width: 34, height: 34, borderRadius: '9px', background: 'rgba(20,184,166,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--teal-primary)', flexShrink: 0 }}>
          {source.connection_id === 'default' ? <Database size={18} /> : <Server size={18} />}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>
            {source.name}
            {source.connector_type === 'sap_s4hana' && (
              <span style={{ marginLeft: '8px', fontSize: '0.62rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(194,120,71,0.14)', color: '#c27847', fontWeight: 700, verticalAlign: 'middle' }}>SAP · ODATA</span>
            )}
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--text-tertiary)' }}>schema <b>{source.schema}</b> · {source.tables} {source.connector_type === 'sap_s4hana' ? 'entity set(s)' : 'table(s)'} · ~{source.total_rows ? source.total_rows.toLocaleString() : 0} rows</div>
        </div>
        <HealthDot ok={source.healthy} />
      </div>
      {source.error && !source.healthy && (
        <div style={{ marginTop: '8px', fontSize: '0.74rem', color: '#dc2626' }}>{String(source.error).slice(0, 120)}</div>
      )}
      <button onClick={onToggle} style={{ ...smallBtn, marginTop: '10px' }}>
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />} {expanded ? 'Hide' : 'Inspect'} catalog
      </button>
      {expanded && (
        <div style={{ marginTop: '10px', borderTop: '1px solid var(--border-card)', paddingTop: '10px' }}>
          {loadingCatalog && <div style={{ display: 'flex', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}><Loader2 className="animate-spin" size={14} /> Introspecting independently…</div>}
          {catalog && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <ShieldCheck size={12} /> {catalog.authz_note} (role: {catalog.role})
              </div>
              {catalog.tables.map((t) => (
                <div key={t.table} style={{ border: '1px solid var(--border-card)', borderRadius: '8px', padding: '8px 10px' }}>
                  <div style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--text-primary)' }}>{t.schema}.{t.table} <span style={{ color: 'var(--text-tertiary)', fontWeight: 400 }}>· {t.row_count || 0} rows</span></div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginTop: '6px' }}>
                    {t.columns.map((c) => (
                      <span key={c.name} title={c.data_type} style={{ fontSize: '0.68rem', padding: '2px 7px', borderRadius: '6px', background: 'rgba(120,120,120,0.1)', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                        {c.name}{c.is_primary_key ? ' 🔑' : c.is_foreign_key ? ' ↳' : ''}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DataSourcesView({ currentRole }) {
  const [sources, setSources] = useState([]);
  const [strategy, setStrategy] = useState('');
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState(null);
  const [catalogs, setCatalogs] = useState({});          // connId -> catalog
  const [expanded, setExpanded] = useState({});          // connId -> bool

  // relationship studio
  const [leftConn, setLeftConn] = useState('default');
  const [leftTable, setLeftTable] = useState('');
  const [rightConn, setRightConn] = useState('');
  const [rightTable, setRightTable] = useState('');
  const [candidates, setCandidates] = useState(null);
  const [findingCandidates, setFindingCandidates] = useState(false);

  const [mappings, setMappings] = useState([]);
  const [joinUI, setJoinUI] = useState({});             // mappingId -> {left:Set, right:Set, type, loading, result}

  const loadMappings = useCallback(async () => {
    const r = await fetch('/api/v1/cross-source/relationships');
    if (r.ok) setMappings((await r.json()).mappings || []);
  }, []);

  const loadCatalog = useCallback(async (connId) => {
    setCatalogs((c) => ({ ...c, [connId]: c[connId] ?? null }));
    const r = await fetch(`/api/v1/cross-source/sources/${connId}/catalog?role=${encodeURIComponent(currentRole)}`);
    const data = r.ok ? await r.json() : { tables: [], role: currentRole };
    setCatalogs((c) => ({ ...c, [connId]: data }));
  }, [currentRole]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [sr] = await Promise.all([fetch('/api/v1/cross-source/sources'), loadMappings()]);
      if (sr.ok) {
        const d = await sr.json();
        setSources(d.sources || []);
        setStrategy(d.strategy || '');
        if (!rightConn && d.sources) {
          const secondary = d.sources.find((s) => s.connection_id !== 'default');
          if (secondary) setRightConn(secondary.connection_id);
        }
      }
    } catch (e) { setNote('Failed to load sources: ' + e.message); }
    finally { setLoading(false); }
  }, [loadMappings, rightConn]);

  useEffect(() => { refresh(); }, []);

  const toggleCatalog = async (connId) => {
    const next = !expanded[connId];
    setExpanded((e) => ({ ...e, [connId]: next }));
    if (next && !catalogs[connId]) await loadCatalog(connId);
  };

  const tablesFor = (connId) => catalogs[connId]?.tables || [];
  const columnsFor = (connId, table) => tablesFor(connId).find((t) => t.table === table)?.columns || [];

  const ensureCatalog = async (connId) => { if (!catalogs[connId]) await loadCatalog(connId); };

  const findCandidates = async () => {
    if (!leftTable || !rightTable) { setNote('Select a table on both sides.'); return; }
    setFindingCandidates(true); setCandidates(null);
    try {
      const r = await fetch('/api/v1/cross-source/relationships/candidates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          left: { connection_id: leftConn, schema_name: catalogs[leftConn]?.schema || 'sales', table_name: leftTable },
          right: { connection_id: rightConn, schema_name: catalogs[rightConn]?.schema || 'inventory', table_name: rightTable },
          role: currentRole,
        }),
      });
      if (r.ok) setCandidates(await r.json());
      else setNote((await r.json()).detail || 'Candidate search failed.');
    } catch (e) { setNote('Candidate search failed: ' + e.message); }
    finally { setFindingCandidates(false); }
  };

  const confirmCandidate = async (cand) => {
    const save = await fetch('/api/v1/cross-source/relationships', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        left_connection_id: cand.left_connection_id, left_schema: cand.left_schema, left_table: cand.left_table, left_column: cand.left_column,
        right_connection_id: cand.right_connection_id, right_schema: cand.right_schema, right_table: cand.right_table, right_column: cand.right_column,
        confidence: cand.confidence, evidence: cand.evidence, created_by: currentRole,
      }),
    });
    if (!save.ok) { setNote('Could not save candidate.'); return; }
    const mid = (await save.json()).id;
    const conf = await fetch(`/api/v1/cross-source/relationships/${mid}/confirm`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed_by: currentRole }),
    });
    if (conf.ok) { setNote('Relationship confirmed and ready to join.'); await loadMappings(); }
    else setNote((await conf.json()).detail || 'Confirmation failed.');
  };

  const deleteMapping = async (id) => {
    await fetch(`/api/v1/cross-source/relationships/${id}`, { method: 'DELETE' });
    setJoinUI((j) => { const n = { ...j }; delete n[id]; return n; });
    loadMappings();
  };

  const initJoinUI = (m) => {
    if (joinUI[m.id]) return;
    ensureCatalog(m.left_connection_id); ensureCatalog(m.right_connection_id);
    setJoinUI((j) => ({ ...j, [m.id]: {
      left: new Set([m.left_column]), right: new Set([m.right_column]), type: 'inner', loading: false, result: null, expanded: true,
    } }));
  };

  const runJoin = async (m) => {
    const ui = joinUI[m.id]; if (!ui) return;
    setJoinUI((j) => ({ ...j, [m.id]: { ...ui, loading: true } }));
    try {
      const r = await fetch('/api/v1/cross-source/join', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({
          mapping_id: m.id, requestor: currentRole,
          left_columns: Array.from(ui.left), right_columns: Array.from(ui.right), join_type: ui.type,
        }),
      });
      const d = await r.json();
      setJoinUI((j) => ({ ...j, [m.id]: { ...ui, loading: false, result: r.ok ? d : { ok: false, error: d.detail || 'Join failed' } } }));
    } catch (e) {
      setJoinUI((j) => ({ ...j, [m.id]: { ...ui, loading: false, result: { ok: false, error: e.message } } }));
    }
  };

  const toggleJoinCol = (m, side, col) => {
    const ui = joinUI[m.id]; const set = new Set(ui[side]);
    set.has(col) ? set.delete(col) : set.add(col);
    setJoinUI((j) => ({ ...j, [m.id]: { ...ui, [side]: set } }));
  };

  const srcName = (connId) => sources.find((s) => s.connection_id === connId)?.name || connId;

  return (
    <div>
      <PageHeader
        icon={Network}
        title="Cross-System Intelligence"
        subtitle="Configure and inspect multiple authorized data sources, discover joinable relationships across them, and run controlled, independently-authorized cross-system queries."
        badge={`${sources.length} source(s)`}
        badgeType="teal"
        actions={<button className="da-btn-secondary" onClick={refresh} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><RefreshCw size={15} /> Refresh</button>}
      />

      {note && (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.24)', color: 'var(--teal-primary)', borderRadius: '10px', padding: '9px 14px', margin: '0 0 16px', fontSize: '0.82rem' }}>
          <AlertTriangle size={15} /> {note}
        </div>
      )}

      {loading && (
        <div style={{ display: 'flex', gap: '10px', color: 'var(--text-secondary)', padding: '24px' }}>
          <Loader2 className="animate-spin" size={18} /> Loading sources…
        </div>
      )}

      {!loading && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(120,120,120,0.06)', border: '1px solid var(--border-card)', borderRadius: '10px', padding: '9px 14px', marginBottom: '16px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            <ShieldCheck size={15} style={{ color: 'var(--teal-primary)' }} />
            Strategy: <b>{strategy.replace(/_/g, ' ')}</b>. Each source is introspected and authorized independently — cross-system results are bounded and never copy unrestricted rows between sources.
          </div>

          <h2 style={{ fontSize: '0.95rem', margin: '0 0 10px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}><Layers size={16} /> Data Sources</h2>
          {sources.map((s) => (
            <SourceCard key={s.connection_id} source={s} catalog={catalogs[s.connection_id]}
              expanded={!!expanded[s.connection_id]} loadingCatalog={!catalogs[s.connection_id]} onToggle={() => toggleCatalog(s.connection_id)} />
          ))}

          {/* SAP S/4HANA enterprise connector — admin management is server-side
              enforced (executive only); hiding this panel is NOT the control. */}
          {currentRole === 'executive' && <SapConnectorPanel onSourcesChanged={refresh} />}

          {/* Relationship studio */}
          <h2 style={{ fontSize: '0.95rem', margin: '22px 0 10px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}><GitBranch size={16} /> Discover Relationships</h2>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '12px', padding: '16px', marginBottom: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              {['left', 'right'].map((side) => {
                const conn = side === 'left' ? leftConn : rightConn;
                const table = side === 'left' ? leftTable : rightTable;
                const setConn = side === 'left' ? setLeftConn : setRightConn;
                const setTable = side === 'left' ? setLeftTable : setRightTable;
                return (
                  <div key={side}>
                    <label style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>{side} source</label>
                    <select value={conn} onChange={async (e) => { setConn(e.target.value); setTable(''); await ensureCatalog(e.target.value); }}
                      style={{ width: '100%', marginTop: '4px', padding: '7px 9px', borderRadius: '8px', border: '1px solid var(--border-card)', background: 'var(--bg-surface)', color: 'var(--text-primary)', fontSize: '0.8rem' }}>
                      {sources.map((s) => <option key={s.connection_id} value={s.connection_id}>{s.name}</option>)}
                    </select>
                    <label style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', display: 'block', marginTop: '8px' }}>{side} table</label>
                    <select value={table} onChange={(e) => setTable(e.target.value)}
                      style={{ width: '100%', marginTop: '4px', padding: '7px 9px', borderRadius: '8px', border: '1px solid var(--border-card)', background: 'var(--bg-surface)', color: 'var(--text-primary)', fontSize: '0.8rem' }}>
                      <option value="">Select table…</option>
                      {tablesFor(conn).map((t) => <option key={t.table} value={t.table}>{t.table}</option>)}
                    </select>
                  </div>
                );
              })}
            </div>
            <button className="btn-primary" onClick={findCandidates} disabled={findingCandidates} style={{ marginTop: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              {findingCandidates ? <Loader2 className="animate-spin" size={15} /> : <Link2 size={15} />} Find candidate relationships
            </button>

            {candidates && (
              <div style={{ marginTop: '14px' }}>
                {candidates.candidate_count === 0 && <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>No compatible columns found between these tables. Nothing was invented.</div>}
                {candidates.candidates.slice(0, 8).map((c, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '9px 12px', border: '1px solid var(--border-card)', borderRadius: '8px', marginBottom: '7px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.78rem', fontFamily: 'monospace', color: 'var(--text-primary)' }}>{c.left_column} ↔ {c.right_column}</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>{c.evidence.reasons.join(', ')}</span>
                    <span style={{ marginLeft: 'auto', fontSize: '0.72rem', fontWeight: 700, color: c.requires_confirmation ? '#f59e0b' : '#10b981' }}>
                      {(c.confidence * 100).toFixed(0)}% {c.requires_confirmation ? '· needs confirm' : '· strong'}
                    </span>
                    <button onClick={() => confirmCandidate(c)} style={smallBtn}><CheckCircle2 size={13} /> Confirm mapping</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Mappings + joins */}
          <h2 style={{ fontSize: '0.95rem', margin: '22px 0 10px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}><Network size={16} /> Confirmed Relationships & Cross-System Queries</h2>
          {mappings.length === 0 && (
            <div style={{ textAlign: 'center', padding: '30px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No relationships yet. Discover candidates above and confirm one to enable a cross-system join.</div>
          )}
          {mappings.map((m) => {
            const ui = joinUI[m.id];
            const lcols = columnsFor(m.left_connection_id, m.left_table).map((c) => c.name);
            const rcols = columnsFor(m.right_connection_id, m.right_table).map((c) => c.name);
            return (
              <div key={m.id} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '12px', padding: '14px 16px', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: m.status === 'confirmed' ? '#10b981' : '#f59e0b' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.84rem', color: 'var(--text-primary)' }}>
                      {srcName(m.left_connection_id)}.<span style={{ fontFamily: 'monospace' }}>{m.left_table}.{m.left_column}</span>
                      {' ↔ '}
                      {srcName(m.right_connection_id)}.<span style={{ fontFamily: 'monospace' }}>{m.right_table}.{m.right_column}</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                      {m.status} · confidence {(m.confidence * 100).toFixed(0)}%
                      {m.confirmed_by ? ` · confirmed by ${m.confirmed_by}` : ''}
                    </div>
                  </div>
                  {m.status === 'confirmed' && (
                    <button onClick={() => ui ? setJoinUI((j) => ({ ...j, [m.id]: { ...ui, expanded: !ui.expanded } })) : initJoinUI(m)} style={smallBtn}>
                      <Play size={13} /> {ui?.expanded ? 'Hide join' : 'Configure join'}
                    </button>
                  )}
                  <button onClick={() => deleteMapping(m.id)} style={{ ...smallBtn, color: '#dc2626' }}><Trash2 size={13} /></button>
                </div>

                {m.status === 'confirmed' && !ui && (
                  <button onClick={() => initJoinUI(m)} style={{ ...smallBtn, marginTop: '10px' }}><Play size={13} /> Configure join</button>
                )}

                {ui && ui.expanded && (
                  <div style={{ marginTop: '12px', borderTop: '1px solid var(--border-card)', paddingTop: '12px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                      {[['left', lcols, m.left_column, 'L'], ['right', rcols, m.right_column, 'R']].map(([side, cols, key, pre]) => (
                        <div key={side}>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', marginBottom: '5px' }}>{pre} · {side} columns</div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                            {cols.map((col) => {
                              const on = ui[side].has(col); const isKey = col === key;
                              return <button key={col} disabled={isKey} onClick={() => toggleJoinCol(m, side, col)} style={{ ...chip(on), opacity: isKey ? 0.7 : 1, cursor: isKey ? 'default' : 'pointer' }}>
                                {col}{isKey ? ' 🔑' : ''}
                              </button>;
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.76rem', color: 'var(--text-secondary)' }}>Join type</span>
                      {joinTypes.map((t) => <button key={t} onClick={() => setJoinUI((j) => ({ ...j, [m.id]: { ...ui, type: t } }))} style={chip(ui.type === t)}>{t}</button>)}
                      <button className="btn-primary" onClick={() => runJoin(m)} disabled={ui.loading} style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {ui.loading ? <Loader2 className="animate-spin" size={14} /> : <Play size={14} />} Run cross-system query
                      </button>
                    </div>

                    {ui.result && ui.result.ok === false && (
                      <div style={{ marginTop: '12px', padding: '10px 12px', borderRadius: '8px', background: 'rgba(220,38,38,0.08)', border: '1px solid rgba(220,38,38,0.24)', color: '#dc2626', fontSize: '0.78rem' }}>
                        {ui.result.error || 'Query failed'}{ui.result.failed_side ? ` (failed source: ${ui.result.failed_side})` : ''}
                      </div>
                    )}

                    {ui.result && ui.result.ok && (
                      <div style={{ marginTop: '12px' }}>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)', marginBottom: '8px' }}>
                          <b>{ui.result.row_count}</b> joined row(s){ui.result.truncated ? ' · truncated at limit' : ''}
                        </div>
                        <div style={{ overflowX: 'auto', border: '1px solid var(--border-card)', borderRadius: '8px' }}>
                          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.74rem' }}>
                            <thead><tr style={{ background: 'rgba(120,120,120,0.06)' }}>
                              {ui.result.columns.map((c) => <th key={c} style={{ textAlign: 'left', padding: '6px 9px', color: c.startsWith('R.') ? '#c27847' : 'var(--teal-primary)', whiteSpace: 'nowrap' }}>{c}</th>)}
                            </tr></thead>
                            <tbody>
                              {ui.result.rows.slice(0, 50).map((row, i) => (
                                <tr key={i} style={{ borderTop: '1px solid var(--border-card)' }}>
                                  {ui.result.columns.map((c) => <td key={c} style={{ padding: '5px 9px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{row[c] == null ? '—' : String(row[c])}</td>)}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {ui.result.rows.length > 50 && <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>Showing first 50 of {ui.result.rows.length} rows.</div>}

                        {/* Lineage */}
                        <div style={{ marginTop: '12px', padding: '12px', borderRadius: '8px', background: 'rgba(120,120,120,0.05)', border: '1px solid var(--border-card)' }}>
                          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}><ShieldCheck size={13} /> Source-level lineage (role: {ui.result.lineage.role_applied})</div>
                          {['left_source', 'right_source'].map((k) => {
                            const s = ui.result.lineage[k]; if (!s) return null;
                            return (
                              <div key={k} style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                                <b>{k.replace('_', ' ')}:</b> {srcName(s.connection_id)} · {s.schema}.{s.table} · {s.returned_rows} row(s){s.truncated ? ' (bounded)' : ''}{s.connector_type === 'sap_s4hana' ? ' · retrieved via OData connector' : ''}
                                <div style={{ fontFamily: 'monospace', color: 'var(--text-tertiary)', fontSize: '0.68rem', marginTop: '2px', wordBreak: 'break-all' }}>
                                  {s.evidence_sql || (s.evidence_request ? `OData request: ${JSON.stringify(s.evidence_request)}` : '')}
                                </div>
                              </div>
                            );
                          })}
                          <div style={{ marginTop: '8px', fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>
                            <b>Limitations:</b>
                            <ul style={{ margin: '4px 0 0', paddingLeft: '18px' }}>
                              {ui.result.limitations.map((l, i) => <li key={i} style={{ marginBottom: '2px' }}>{l}</li>)}
                            </ul>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
