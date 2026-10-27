import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Network, GitBranch, Plus, Send, Archive, Edit3, Check, Sparkles,
  AlertTriangle, Layers, Loader2, ShieldCheck, TrendingUp, TrendingDown, X,
} from 'lucide-react';
import PageHeader from './PageHeader';

const fmtVal = (n) => {
  const v = Number(n || 0);
  if (Math.abs(v) >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
  if (Math.abs(v) >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
  return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
};

function InlineBar({ rows }) {
  const data = (rows || []).slice(0, 8);
  if (data.length < 2) return null;
  const cols = Object.keys(data[0] || {});
  const labelCol = cols.find((c) => typeof data[0][c] === 'string') || cols[0];
  const valCol = cols.find((c) => c !== labelCol && !Number.isNaN(Number(data[0][c]))) || cols[1];
  const vals = data.map((d) => Number(d[valCol] || 0));
  const max = Math.max(...vals.map(Math.abs)) || 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '8px' }}>
      {data.map((d, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ width: '96px', fontSize: '0.68rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(d[labelCol] ?? '')}>{String(d[labelCol] ?? '')}</span>
          <div style={{ flex: 1, height: '12px', background: 'rgba(17,94,89,0.08)', borderRadius: '3px' }}>
            <div style={{ width: `${(Math.abs(vals[i]) / max) * 100}%`, height: '100%', borderRadius: '3px', background: 'linear-gradient(90deg,#115e59,#2dd4bf)' }} />
          </div>
          <span style={{ width: '70px', textAlign: 'right', fontSize: '0.66rem', color: 'var(--text-muted)' }}>{fmtVal(vals[i])}</span>
        </div>
      ))}
    </div>
  );
}

function EvidenceTurn({ turn }) {
  const [open, setOpen] = useState(false);
  const ok = turn.status === 'completed';
  return (
    <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '8px 10px', background: 'var(--bg-secondary)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-headings)', fontWeight: 600 }}>{turn.question}</div>
        <span style={{ fontSize: '0.6rem', fontWeight: 700, textTransform: 'uppercase', color: ok ? '#10b981' : turn.status === 'clarification_needed' ? '#f59e0b' : '#ef4444', whiteSpace: 'nowrap' }}>{turn.status?.replace(/_/g, ' ')}</span>
      </div>
      {turn.explanation && <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.45 }}>{turn.explanation}</div>}
      {ok && (
        <>
          <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '6px' }}>{turn.row_count} rows · {((turn.execution_time_ms || 0) / 1000).toFixed(2)}s</div>
          <InlineBar rows={turn.rows} />
          <button onClick={() => setOpen((v) => !v)} style={{ marginTop: '6px', background: 'none', border: 'none', color: 'var(--teal-primary)', fontSize: '0.68rem', fontWeight: 600, cursor: 'pointer', padding: 0 }}>
            {open ? 'Hide SQL & data' : 'Show SQL & data'}
          </button>
          {open && (
            <div style={{ marginTop: '6px' }}>
              <pre style={{ margin: 0, padding: '8px', background: '#0f1a1e', color: '#a5f3fc', borderRadius: '6px', fontSize: '0.66rem', overflowX: 'auto', fontFamily: 'var(--font-mono)' }}>{turn.sql}</pre>
              {turn.rows?.length > 0 && (
                <div style={{ overflowX: 'auto', marginTop: '6px', maxHeight: '180px' }}>
                  <table style={{ borderCollapse: 'collapse', fontSize: '0.66rem', width: '100%' }}>
                    <thead><tr>{(turn.columns || []).map((c) => <th key={c} style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-card)' }}>{typeof c === 'string' ? c : c.name}</th>)}</tr></thead>
                    <tbody>{turn.rows.slice(0, 20).map((r, i) => (<tr key={i}>{(turn.columns || []).map((c) => { const k = typeof c === 'string' ? c : c.name; return <td key={k} style={{ padding: '3px 6px', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-subtle)', whiteSpace: 'nowrap' }}>{String(r[k] ?? '')}</td>; })}</tr>))}</tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function BranchCard({ branch, tree, turnsByBranch, depth, busy, onAsk, onAddBranch, onRename, onArchive, onConclusion }) {
  const [q, setQ] = useState(branch.seed_question || '');
  const [concl, setConcl] = useState(branch.conclusion || '');
  const turns = turnsByBranch[branch.id] || [];
  const archived = branch.status === 'archived';
  return (
    <div style={{ marginLeft: depth * 18, border: '1px solid var(--border-card)', borderLeft: `3px solid ${branch.origin === 'root_cause' ? 'var(--copper-primary)' : 'var(--teal-primary)'}`, borderRadius: '10px', background: archived ? 'var(--bg-secondary)' : 'var(--bg-surface)', padding: '10px 12px', opacity: archived ? 0.7 : 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', minWidth: 0 }}>
          <GitBranch size={14} style={{ color: branch.origin === 'root_cause' ? 'var(--copper-primary)' : 'var(--teal-primary)', flexShrink: 0 }} />
          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-headings)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{branch.title}</span>
          {branch.contributor_segment && <span style={{ fontSize: '0.6rem', background: 'rgba(194,120,71,0.14)', color: 'var(--copper-dark)', padding: '1px 6px', borderRadius: '999px', fontWeight: 700 }}>{branch.contributor_segment}</span>}
        </div>
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          <button title="Rename" onClick={() => onRename(branch)} style={iconBtn}><Edit3 size={12} /></button>
          <button title="Add parallel branch" onClick={() => onAddBranch(branch)} style={iconBtn}><Plus size={13} /></button>
          <button title={archived ? 'Reopen' : 'Archive'} onClick={() => onArchive(branch)} style={iconBtn}><Archive size={12} /></button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
        {(turns || []).map((t) => <EvidenceTurn key={t.id} turn={t} />)}
        {(!turns || turns.length === 0) && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No analysis yet — ask a question to run an authorized query in this branch.</div>}
      </div>

      <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && q.trim()) { onAsk(branch, q.trim()); setQ(''); } }} placeholder={branch.seed_question ? 'Follow-up in this branch…' : 'Ask this branch a question…'} disabled={archived || busy === branch.id} style={{ flex: 1, padding: '7px 10px', borderRadius: '8px', border: '1px solid var(--border-card)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.78rem', outline: 'none' }} />
        <button onClick={() => { if (q.trim()) { onAsk(branch, q.trim()); setQ(''); } }} disabled={archived || busy === branch.id} className="btn-primary" style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.76rem' }}>
          {busy === branch.id ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Ask
        </button>
      </div>

      <div style={{ display: 'flex', gap: '6px', marginTop: '6px', alignItems: 'center' }}>
        <input value={concl} onChange={(e) => setConcl(e.target.value)} placeholder="Conclusion for this branch (optional)…" disabled={archived} style={{ flex: 1, padding: '6px 10px', borderRadius: '8px', border: '1px dashed var(--border-card)', background: 'transparent', color: 'var(--text-secondary)', fontSize: '0.72rem', outline: 'none' }} />
        <button onClick={() => onConclusion(branch, concl)} disabled={archived || !concl.trim()} style={{ ...iconBtn, border: '1px solid var(--border-card)' }} title="Save conclusion"><Check size={13} /></button>
      </div>

      {(tree[branch.id] || []).map((child) => (
        <div key={child.id} style={{ marginTop: '8px' }}>
          <BranchCard branch={child} tree={tree} turnsByBranch={turnsByBranch} depth={depth + 1}
            busy={busy} onAsk={onAsk} onAddBranch={onAddBranch} onRename={onRename}
            onArchive={onArchive} onConclusion={onConclusion} />
        </div>
      ))}
    </div>
  );
}

const iconBtn = { background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '4px', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', alignItems: 'center' };

export default function InvestigationView({ currentRole = 'executive', focusId = null }) {
  const [list, setList] = useState([]);
  const [detail, setDetail] = useState(null);
  const [turnsByBranch, setTurnsByBranch] = useState({});
  const [busy, setBusy] = useState(null);
  const [findings, setFindings] = useState([]);
  const [newFindingId, setNewFindingId] = useState('');
  const [loading, setLoading] = useState(false);

  const loadList = useCallback(async () => {
    const res = await fetch('/api/v1/investigations');
    if (res.ok) setList((await res.json()).investigations || []);
  }, []);

  const loadFindings = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/discover/findings?status=active&limit=50');
      if (res.ok) setFindings((await res.json()).findings || []);
    } catch { /* ignore */ }
  }, []);

  const loadDetail = useCallback(async (id) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/v1/investigations/${id}`);
      if (res.ok) {
        const d = await res.json();
        setDetail(d);
        const t = {};
        await Promise.all((d.branches || []).map(async (b) => {
          const tr = await fetch(`/api/v1/investigations/${id}/branches/${b.id}/turns`);
          if (tr.ok) t[b.id] = (await tr.json()).turns || [];
        }));
        setTurnsByBranch(t);
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadList(); loadFindings(); }, [loadList, loadFindings]);
  useEffect(() => { if (focusId) loadDetail(focusId); }, [focusId, loadDetail]);

  const tree = useMemo(() => {
    const map = {};
    (detail?.branches || []).forEach((b) => { const p = b.parent_branch_id || '__root__'; (map[p] = map[p] || []).push(b); });
    return map;
  }, [detail]);

  const roots = tree['__root__'] || [];

  const openInvestigation = async (findingId) => {
    if (!findingId) return;
    const res = await fetch('/api/v1/investigations', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
      body: JSON.stringify({ finding_id: findingId, role: currentRole }),
    });
    if (res.ok) { const d = await res.json(); setDetail(d); setNewFindingId(''); loadList(); await loadDetail(d.id); }
  };

  const askBranch = async (branch, question) => {
    setBusy(branch.id);
    try {
      await fetch('/api/v1/queries', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ question, session_id: branch.session_id, user_role: currentRole, connection_id: 'default' }),
      });
      const tr = await fetch(`/api/v1/investigations/${detail.id}/branches/${branch.id}/turns`);
      if (tr.ok) {
        const data = await tr.json();
        setTurnsByBranch((prev) => ({ ...prev, [branch.id]: data.turns || [] }));
      }
    } finally { setBusy(null); }
  };

  const addBranch = async (parent) => {
    const title = window.prompt('Name this parallel hypothesis / branch:');
    if (!title) return;
    const question = window.prompt('Opening question (optional):') || '';
    await fetch(`/api/v1/investigations/${detail.id}/branches`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, question, parent_branch_id: parent?.id || null, origin: 'manual' }),
    });
    await loadDetail(detail.id);
  };

  const renameBranch = async (branch) => {
    const title = window.prompt('Rename branch:', branch.title);
    if (!title) return;
    await fetch(`/api/v1/investigations/${detail.id}/branches/${branch.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
    });
    await loadDetail(detail.id);
  };

  const archiveBranch = async (branch) => {
    await fetch(`/api/v1/investigations/${detail.id}/branches/${branch.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: branch.status === 'archived' ? 'open' : 'archived' }),
    });
    await loadDetail(detail.id);
  };

  const saveConclusion = async (branch, conclusion) => {
    await fetch(`/api/v1/investigations/${detail.id}/branches/${branch.id}/conclusion`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conclusion }),
    });
    await loadDetail(detail.id);
  };

  const rc = detail?.root_cause_runs?.[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem', width: '100%', maxWidth: '1360px', margin: '0 auto' }}>
      <PageHeader
        icon={Network}
        title="Investigation Workspace"
        subtitle="Open a Discover finding as a branching investigation. Explore multiple contributing hypotheses in parallel — each keeps its own context, SQL, evidence and conclusion."
        badge={`${list.length} investigations`}
        badgeType="teal"
      />

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '0.7rem 1rem' }}>
        <Sparkles size={15} style={{ color: 'var(--teal-primary)' }} />
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>New investigation from a finding:</span>
        <select value={newFindingId} onChange={(e) => setNewFindingId(e.target.value)} style={{ flex: 1, minWidth: '220px', padding: '7px 10px', borderRadius: '8px', border: '1px solid var(--border-card)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.78rem' }}>
          <option value="">Select a finding…</option>
          {findings.map((f) => <option key={f.id} value={f.id}>{f.title}</option>)}
        </select>
        <button className="btn-primary" onClick={() => openInvestigation(newFindingId)} disabled={!newFindingId} style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}>
          <GitBranch size={14} /> Open Investigation
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '1rem', alignItems: 'start' }}>
        {/* Investigations list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {list.length === 0 && <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', padding: '12px', textAlign: 'center' }}>No investigations yet. Open one from a finding above.</div>}
          {list.map((i) => (
            <button key={i.id} onClick={() => loadDetail(i.id)} style={{ textAlign: 'left', padding: '10px 12px', borderRadius: '10px', cursor: 'pointer', border: detail?.id === i.id ? '1px solid rgba(17,94,89,0.4)' : '1px solid var(--border-card)', background: detail?.id === i.id ? 'rgba(17,94,89,0.08)' : 'var(--bg-surface)' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-headings)', lineHeight: 1.3 }}>{i.title}</div>
              <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '3px' }}>{i.branch_count} branches · {i.role.replace(/_/g, ' ')}</div>
            </button>
          ))}
        </div>

        {/* Detail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', minWidth: 0 }}>
          {!detail ? (
            <div style={{ padding: '3rem 1rem', textAlign: 'center', border: '1px dashed var(--border-card)', borderRadius: 'var(--radius-lg)', color: 'var(--text-muted)' }}>
              <Network size={36} style={{ marginBottom: '10px', opacity: 0.5 }} />
              <div style={{ fontSize: '0.9rem' }}>Select an investigation, or open one from a Discover finding.</div>
            </div>
          ) : (
            <>
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: '1.1rem', color: 'var(--text-headings)' }}>{detail.title}</h2>
                {detail.narrative && <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{detail.narrative}</p>}
              </div>

              {/* Root-cause panel */}
              {rc && (
                <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: 'var(--radius-lg)', padding: '0.9rem 1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <Layers size={15} style={{ color: 'var(--copper-primary)' }} />
                    <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-headings)' }}>Root-Cause Exploration</span>
                    <span style={{ fontSize: '0.62rem', fontWeight: 700, padding: '2px 7px', borderRadius: '999px', background: rc.reconciles ? 'rgba(16,185,129,0.14)' : 'rgba(245,158,11,0.14)', color: rc.reconciles ? '#10b981' : '#f59e0b' }}>{rc.reconciles ? 'Contributions reconcile' : 'Partial'}</span>
                  </div>
                  {rc.evidence?.summary && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '8px' }}>{rc.evidence.summary}</div>}
                  {(rc.contributions || []).slice(0, 6).map((c, i) => {
                    const up = c.change_abs >= 0;
                    return (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                        {up ? <TrendingUp size={13} color="#10b981" /> : <TrendingDown size={13} color="#ef4444" />}
                        <span style={{ flex: 1, fontSize: '0.76rem', color: 'var(--text-headings)', fontWeight: 600 }}>{c.segment}</span>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{fmtVal(c.baseline_value)} → {fmtVal(c.current_value)}</span>
                        <span style={{ fontSize: '0.72rem', fontWeight: 700, width: '70px', textAlign: 'right', color: up ? '#10b981' : '#ef4444' }}>{c.contribution_pct}%</span>
                      </div>
                    );
                  })}
                  {rc.evidence?.limitations?.length > 0 && (
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', marginTop: '8px', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                      <AlertTriangle size={12} style={{ marginTop: '1px', flexShrink: 0 }} />
                      <span>{rc.evidence.limitations[0]} {rc.evidence.fact_vs_hypothesis ? `· ${rc.evidence.fact_vs_hypothesis}` : ''}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Branch tree */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-headings)', display: 'flex', alignItems: 'center', gap: '6px' }}><ShieldCheck size={14} style={{ color: 'var(--teal-primary)' }} /> Investigation branches</span>
                <button onClick={() => addBranch(null)} style={{ padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.74rem', background: 'var(--bg-surface)', color: 'var(--teal-primary)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}><Plus size={13} /> Add branch</button>
              </div>

              {loading ? (
                <div style={{ padding: '2rem', textAlign: 'center' }}><Loader2 size={22} className="animate-spin" color="var(--teal-primary)" /></div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {roots.map((b) => (
                    <BranchCard key={b.id} branch={b} tree={tree} turnsByBranch={turnsByBranch} depth={0}
                      busy={busy} onAsk={askBranch} onAddBranch={addBranch}
                      onRename={renameBranch} onArchive={archiveBranch} onConclusion={saveConclusion} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
