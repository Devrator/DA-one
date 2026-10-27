import React, { useState, useEffect, useCallback } from 'react';
import {
  Inbox, RefreshCw, Settings2, Loader2, Network, ChevronDown, ChevronUp,
  TrendingUp, TrendingDown, AlertTriangle, CalendarClock, CheckCircle2, Bell, SlidersHorizontal,
} from 'lucide-react';
import PageHeader from './PageHeader';

const SEV = {
  critical: { c: '#ef4444', label: 'Critical' },
  warning: { c: '#f59e0b', label: 'Warning' },
  watch: { c: '#38bdf8', label: 'Watch' },
  info: { c: '#10b981', label: 'Info' },
};
const CATEGORIES = ['trend', 'anomaly', 'concentration', 'underperformer', 'opportunity'];

const fmtVal = (n) => {
  const v = Number(n || 0);
  if (Math.abs(v) >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
  if (Math.abs(v) >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
  return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
};

function BriefingItem({ item, onOpenInvestigation }) {
  const sev = SEV[item.severity] || SEV.info;
  const up = (item.delta_pct || 0) >= 0;
  const Arrow = up ? TrendingUp : TrendingDown;
  return (
    <div style={{ border: '1px solid var(--border-card)', borderLeft: `3px solid ${sev.c}`, borderRadius: '10px', padding: '12px 14px', marginBottom: '10px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.62rem', fontWeight: 700, color: sev.c, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{sev.label}</span>
        <span style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>{item.finding_type}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px', color: up ? '#10b981' : '#dc2626', fontWeight: 700, fontSize: '0.8rem' }}>
          <Arrow size={13} /> {up ? '+' : ''}{(item.delta_pct || 0).toFixed(1)}%
        </span>
      </div>
      <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)', margin: '6px 0 4px' }}>{item.title}</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{item.narrative}</div>
      {item.suggested_next_steps && (
        <div style={{ fontSize: '0.74rem', color: 'var(--text-tertiary)', marginTop: '6px' }}>
          <b>Next:</b> {item.suggested_next_steps}
        </div>
      )}
      <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={() => onOpenInvestigation && onOpenInvestigation(item.finding_id)}
          style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px', fontSize: '0.76rem', color: 'var(--teal-primary)', background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '8px', cursor: 'pointer' }}>
          <Network size={13} /> Open in Investigation
        </button>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>
          {fmtVal(item.baseline_value)} → {fmtVal(item.current_value)} · {item.comparison_label || item.period_label || ''}
        </span>
      </div>
    </div>
  );
}

function BriefingCard({ briefing, onOpenInvestigation }) {
  const [expanded, setExpanded] = useState(false);
  const [full, setFull] = useState(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !full) {
      setLoading(true);
      try {
        const r = await fetch(`/api/v1/briefings/${briefing.id}`);
        if (r.ok) setFull(await r.json());
        if (briefing.status !== 'read') fetch(`/api/v1/briefings/${briefing.id}/status/read`, { method: 'POST' });
      } catch (e) { /* ignore */ }
      finally { setLoading(false); }
    }
  };

  const items = full?.items || [];
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '12px', padding: '16px', marginBottom: '14px' }}>
      <div onClick={toggle} style={{ cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
        <div style={{ width: 34, height: 34, borderRadius: '9px', background: 'rgba(20,184,166,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--teal-primary)', flexShrink: 0 }}>
          {briefing.status === 'read' ? <CheckCircle2 size={18} /> : <Bell size={18} />}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: '0.92rem', color: 'var(--text-primary)' }}>{briefing.subject}</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>{briefing.summary}</div>
          <div style={{ display: 'flex', gap: '12px', marginTop: '6px', fontSize: '0.7rem', color: 'var(--text-tertiary)', flexWrap: 'wrap' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><CalendarClock size={12} /> {briefing.cadence} · {briefing.period_label}</span>
            <span>{briefing.item_count} item(s)</span>
            {briefing.suppressed_count > 0 && <span>{briefing.suppressed_count} suppressed (dup/stale/low)</span>}
            {briefing.source_data_freshness_at && <span>fresh {new Date(briefing.source_data_freshness_at).toLocaleDateString()}</span>}
          </div>
        </div>
        {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </div>
      {expanded && (
        <div style={{ marginTop: '14px', borderTop: '1px solid var(--border-card)', paddingTop: '12px' }}>
          {loading && <div style={{ display: 'flex', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}><Loader2 className="animate-spin" size={15} /> Loading…</div>}
          {!loading && briefing.status === 'empty' && (
            <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>No material changes were found in your authorized scope. Nothing was invented to fill this briefing.</div>
          )}
          {!loading && items.map((it, i) => <BriefingItem key={i} item={it} onOpenInvestigation={onOpenInvestigation} />)}
        </div>
      )}
    </div>
  );
}

export default function BriefingInboxView({ currentRole, onOpenInvestigation }) {
  const [briefings, setBriefings] = useState([]);
  const [pref, setPref] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [note, setNote] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [ib, pb] = await Promise.all([
        fetch(`/api/v1/briefings/inbox?username=${encodeURIComponent(currentRole)}`),
        fetch(`/api/v1/briefings/preferences?username=${encodeURIComponent(currentRole)}`),
      ]);
      if (ib.ok) setBriefings((await ib.json()).briefings || []);
      if (pb.ok) setPref(await pb.json());
    } catch (e) { setNote('Failed to load briefings: ' + e.message); }
    finally { setLoading(false); }
  }, [currentRole]);

  useEffect(() => { refresh(); }, [refresh]);

  const generateNow = async () => {
    setGenerating(true); setNote(null);
    try {
      const r = await fetch('/api/v1/briefings/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
        body: JSON.stringify({ username: currentRole, cadence: 'manual', refresh: true }),
      });
      const d = await r.json();
      if (!r.ok) { setNote(d.detail || 'Generation failed.'); }
      else if (d.status === 'deduped') { setNote('Up to date — no new material findings for this period.'); }
      else { setNote(d.status === 'empty' ? 'Checked fresh data: no material changes in your scope.' : `Briefing generated with ${d.item_count} item(s).`); }
      refresh();
    } catch (e) { setNote('Generation failed: ' + e.message); }
    finally { setGenerating(false); }
  };

  const savePrefs = async (patch) => {
    const body = { username: currentRole, ...patch };
    const r = await fetch('/api/v1/briefings/preferences', {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
      body: JSON.stringify(body),
    });
    if (r.ok) { setPref(await r.json()); setNote('Preferences saved.'); }
  };

  const toggleCategory = (cat) => {
    const cur = new Set(pref?.enabled_categories || CATEGORIES);
    cur.has(cat) ? cur.delete(cat) : cur.add(cat);
    savePrefs({ enabled_categories: Array.from(cur) });
  };

  return (
    <div>
      <PageHeader
        icon={Inbox}
        title="Personalized Briefings"
        subtitle={`Role-aware intelligence for ${pref?.role || currentRole} — generated only from data your authorization scope can see.`}
        badge={`${briefings.length} in inbox`}
        badgeType="teal"
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <button className="da-btn-secondary" onClick={() => setShowSettings((v) => !v)} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Settings2 size={15} /> Preferences
            </button>
            <button className="btn-primary" onClick={generateNow} disabled={generating} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {generating ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />} Generate now
            </button>
          </div>
        }
      />

      {note && (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.24)', color: 'var(--teal-primary)', borderRadius: '10px', padding: '9px 14px', margin: '0 0 16px', fontSize: '0.82rem' }}>
          <AlertTriangle size={15} /> {note}
        </div>
      )}

      {showSettings && pref && (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-card)', borderRadius: '12px', padding: '16px', marginBottom: '18px' }}>
          <h3 style={{ margin: '0 0 10px', fontSize: '0.9rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}><SlidersHorizontal size={16} /> Briefing preferences</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Frequency</span>
            {['daily', 'weekly', 'disabled'].map((f) => (
              <button key={f} onClick={() => savePrefs({ frequency: f })}
                style={{ padding: '5px 12px', fontSize: '0.78rem', borderRadius: '8px', cursor: 'pointer', textTransform: 'capitalize',
                  border: `1px solid ${pref.frequency === f ? 'var(--teal-primary)' : 'var(--border-card)'}`,
                  background: pref.frequency === f ? 'rgba(20,184,166,0.12)' : 'var(--bg-surface)',
                  color: pref.frequency === f ? 'var(--teal-primary)' : 'var(--text-secondary)' }}>{f}</button>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Categories</span>
            {CATEGORIES.map((c) => {
              const on = (pref.enabled_categories || CATEGORIES).includes(c);
              return (
                <button key={c} onClick={() => toggleCategory(c)}
                  style={{ padding: '4px 10px', fontSize: '0.74rem', borderRadius: '14px', cursor: 'pointer', textTransform: 'capitalize',
                    border: `1px solid ${on ? 'var(--copper-primary, #c27847)' : 'var(--border-card)'}`,
                    background: on ? 'rgba(194,120,71,0.12)' : 'transparent', color: on ? 'var(--copper-primary, #c27847)' : 'var(--text-tertiary)' }}>{c}</button>
              );
            })}
          </div>
        </div>
      )}

      {loading && (
        <div style={{ display: 'flex', gap: '10px', color: 'var(--text-secondary)', padding: '24px' }}>
          <Loader2 className="animate-spin" size={18} /> Loading your briefings…
        </div>
      )}

      {!loading && briefings.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-secondary)' }}>
          <Inbox size={40} style={{ opacity: 0.4 }} />
          <p style={{ marginTop: '12px', fontSize: '0.9rem' }}>No briefings yet. Press <b>Generate now</b> to build one from your authorized, live data.</p>
        </div>
      )}

      {!loading && briefings.map((b) => (
        <BriefingCard key={b.id} briefing={b} onOpenInvestigation={onOpenInvestigation} />
      ))}
    </div>
  );
}
