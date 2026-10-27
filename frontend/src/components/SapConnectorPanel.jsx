import { useState, useEffect, useCallback } from 'react';
import {
  PlugZap, Loader2, CheckCircle2, XCircle, RefreshCw, Ban,
  ChevronDown, ChevronUp, Eye, KeyRound, Boxes, ShieldCheck, ArrowRight, Plus,
} from 'lucide-react';

// Roles an admin can preview SAP data as (server re-resolves on every call —
// this dropdown only sets the X-User-Role header; the backend is the authority).
const SAP_ROLES = ['executive', 'regional_manager', 'sales_rep'];

const lifecycleStyle = {
  configured: { bg: 'rgba(245,158,11,0.14)', color: '#b45309', label: 'Configured' },
  connected: { bg: 'rgba(16,185,129,0.14)', color: '#059669', label: 'Connected' },
  degraded: { bg: 'rgba(220,38,38,0.12)', color: '#dc2626', label: 'Degraded' },
  disabled: { bg: 'rgba(120,120,120,0.14)', color: '#6b7280', label: 'Disabled' },
};

const btn = {
  display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '5px 11px',
  fontSize: '0.76rem', borderRadius: '8px', cursor: 'pointer', border: '1px solid var(--border-card)',
  background: 'var(--bg-surface)', color: 'var(--teal-primary)',
};
const dangerBtn = { ...btn, color: '#dc2626' };
const inputStyle = {
  width: '100%', marginTop: '4px', padding: '7px 9px', borderRadius: '8px',
  border: '1px solid var(--border-card)', background: 'var(--bg-surface)',
  color: 'var(--text-primary)', fontSize: '0.8rem', boxSizing: 'border-box',
};
const labelStyle = { fontSize: '0.72rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', display: 'block', marginTop: '10px' };

// Every SAP management call goes through here. The backend enforces
// executive-only admin on each endpoint regardless of these headers.
async function sapJson(url, options = {}) {
  try {
    const r = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-User-Role': 'executive',
        ...(options.headers || {}),
      },
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: data.detail || `Request failed (HTTP ${r.status})`, status: r.status };
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

function ErrorLine({ msg }) {
  if (!msg) return null;
  return (
    <div style={{ marginTop: '10px', padding: '8px 11px', borderRadius: '8px', background: 'rgba(220,38,38,0.08)', border: '1px solid rgba(220,38,38,0.24)', color: '#dc2626', fontSize: '0.76rem', display: 'flex', gap: '7px', alignItems: 'flex-start' }}>
      <XCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} /> {String(msg).slice(0, 300)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connection wizard — deployment → network → auth → real test → create+discover
// "Create" stays disabled until a live test returns success: no fake passes.
// ---------------------------------------------------------------------------

function SapWizard({ onDone, onCancel }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({
    name: '', deployment_type: 'public_cloud',
    base_url: '', service_path: '', odata_version: '4', tls_verify: true,
    auth_mode: 'basic', username: '', secret: '',
    oauth_client_id: '', oauth_scope: '', oauth_token_url: '', secret_ref: '',
  });
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);   // {success, message, ...}
  const [createResult, setCreateResult] = useState(null);
  const [error, setError] = useState(null);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  // Payload WITHOUT the connection name (test endpoint shares the base schema).
  const payload = () => {
    const p = {
      deployment_type: form.deployment_type,
      base_url: form.base_url,
      service_path: form.service_path,
      odata_version: form.odata_version,
      auth_mode: form.auth_mode,
      username: form.auth_mode === 'basic' ? form.username : '',
      secret: form.secret,
      tls_verify: form.tls_verify,
      secret_ref: form.secret_ref || null,
    };
    if (form.auth_mode === 'oauth_client_credentials') {
      p.oauth_client_id = form.oauth_client_id || null;
      p.oauth_scope = form.oauth_scope || null;
      p.oauth_token_url = form.oauth_token_url || null;
    }
    return p;
  };

  const stepValid = (s) => {
    if (s === 1) return form.name.trim().length > 0;
    if (s === 2) return form.base_url.trim().length >= 8;
    if (s === 3) {
      if (!form.secret) return false;
      if (form.auth_mode === 'basic') return form.username.trim().length > 0;
      return !!form.oauth_client_id && !!form.oauth_token_url;
    }
    return true;
  };

  const runTest = async () => {
    setBusy(true); setError(null); setTestResult(null);
    const r = await sapJson('/api/v1/connections/sap/test', { method: 'POST', body: JSON.stringify(payload()) });
    setBusy(false);
    if (!r.ok) { setError(r.error); return; }
    setTestResult(r.data);
  };

  const createAndDiscover = async () => {
    setBusy(true); setError(null);
    const created = await sapJson('/api/v1/connections/sap', {
      method: 'POST', body: JSON.stringify({ ...payload(), name: form.name }),
    });
    if (!created.ok) { setBusy(false); setError(created.error); return; }
    const conn = created.data;
    // Immediate real discovery so the source is usable right away.
    const refresh = await sapJson(`/api/v1/connections/${conn.id}/schema/refresh`, { method: 'POST' });
    setBusy(false);
    setCreateResult({
      connection: conn,
      discovery: refresh.ok ? refresh.data : null,
      discoveryError: refresh.ok ? null : refresh.error,
    });
    onDone();  // refresh the management list + cross-source catalog
  };

  const stepTitles = ['Deployment', 'SAP endpoint & network', 'Authentication', 'Test, then create'];

  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid rgba(194,120,71,0.4)', borderRadius: '12px', padding: '16px', marginTop: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
        <PlugZap size={17} style={{ color: '#c27847' }} />
        <b style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>Connect SAP S/4HANA (read-only)</b>
        <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>Step {step} of 4 · {stepTitles[step - 1]}</span>
      </div>
      <div style={{ display: 'flex', gap: '4px', margin: '8px 0 14px' }}>
        {[1, 2, 3, 4].map((s) => (
          <div key={s} style={{ flex: 1, height: 4, borderRadius: 2, background: s <= step ? '#c27847' : 'var(--border-card)' }} />
        ))}
      </div>

      {step === 1 && (
        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Name this source and choose where SAP S/4HANA runs. All connectivity is via released OData APIs — the connector is strictly read-only.</div>
          <label style={labelStyle}>Connection name</label>
          <input style={inputStyle} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. S/4 Sales Analytics (Prod)" />
          <label style={labelStyle}>Deployment</label>
          <select style={inputStyle} value={form.deployment_type} onChange={(e) => set('deployment_type', e.target.value)}>
            <option value="public_cloud">SAP Public Cloud (S/4HANA Cloud)</option>
            <option value="private_cloud">SAP Private Cloud</option>
            <option value="on_premises">On-premise / on the network</option>
            <option value="hybrid">Hybrid (VPN / private link)</option>
          </select>
        </div>
      )}

      {step === 2 && (
        <div>
          <div style={{ display: 'flex', gap: '7px', alignItems: 'flex-start', background: 'rgba(120,120,120,0.06)', border: '1px solid var(--border-card)', borderRadius: '8px', padding: '8px 11px', marginTop: '6px', fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
            <ShieldCheck size={13} style={{ color: 'var(--teal-primary)', flexShrink: 0, marginTop: 2 }} />
            Targets are fail-closed: the host must be pre-approved in the server-side <b>SAP_ALLOWED_HOSTS</b> allowlist (and reachable from this server's network — see the admin guide for hybrid prerequisites). Cloud-metadata endpoints are always blocked.
          </div>
          <label style={labelStyle}>Base URL (https://host/apiroot)</label>
          <input style={inputStyle} value={form.base_url} onChange={(e) => set('base_url', e.target.value)} placeholder="https://my-api.s4sap.example.com/sap/opu/odata4/sap" />
          <label style={labelStyle}>Service path (optional, appended to base URL)</label>
          <input style={inputStyle} value={form.service_path} onChange={(e) => set('service_path', e.target.value)} placeholder="e.g. /I_SalesOrder_SRV" />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={labelStyle}>OData version</label>
              <select style={inputStyle} value={form.odata_version} onChange={(e) => set('odata_version', e.target.value)}>
                <option value="4">V4</option>
                <option value="2">V2</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>TLS certificate verification</label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '10px', fontSize: '0.8rem', color: 'var(--text-primary)', cursor: 'pointer' }}>
                <input type="checkbox" checked={form.tls_verify} onChange={(e) => set('tls_verify', e.target.checked)} /> Verify (recommended; keep on unless your SAP gateway uses an internal CA)
              </label>
            </div>
          </div>
        </div>
      )}

      {step === 3 && (
        <div>
          <label style={{ ...labelStyle, marginTop: 0 }}>Authentication mode</label>
          <select style={inputStyle} value={form.auth_mode} onChange={(e) => { set('auth_mode', e.target.value); setTestResult(null); }}>
            <option value="basic">Basic (SAP communication user, read-only)</option>
            <option value="oauth_client_credentials">OAuth2 client credentials (service user technical)</option>
          </select>
          {form.auth_mode === 'basic' ? (
            <>
              <label style={labelStyle}>SAP username</label>
              <input style={inputStyle} value={form.username} onChange={(e) => set('username', e.target.value)} autoComplete="off" />
            </>
          ) : (
            <>
              <label style={labelStyle}>OAuth client ID</label>
              <input style={inputStyle} value={form.oauth_client_id} onChange={(e) => set('oauth_client_id', e.target.value)} autoComplete="off" />
              <label style={labelStyle}>Token URL (must also be allowlisted)</label>
              <input style={inputStyle} value={form.oauth_token_url} onChange={(e) => set('oauth_token_url', e.target.value)} placeholder="https://<auth-host>/oauth/token" />
              <label style={labelStyle}>Scope (optional)</label>
              <input style={inputStyle} value={form.oauth_scope} onChange={(e) => set('oauth_scope', e.target.value)} placeholder="openid" />
            </>
          )}
          <label style={labelStyle}>{form.auth_mode === 'basic' ? 'Password / app password' : 'Client secret'}</label>
          <input type="password" style={inputStyle} value={form.secret} onChange={(e) => set('secret', e.target.value)} autoComplete="new-password" placeholder="Stored encrypted (Fernet) — never shown again" />
          <label style={labelStyle}>Credential reference (optional label for rotation)</label>
          <input style={inputStyle} value={form.secret_ref} onChange={(e) => set('secret_ref', e.target.value)} placeholder="e.g. vault:prod/sap-readonly" />
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: '8px' }}>The secret is encrypted at rest on save and redacted from every log, error and API response. Use a <b>read-only</b> SAP identity — QueryPilot policy applies IN ADDITION to SAP-side authorizations.</div>
        </div>
      )}

      {step === 4 && (
        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>This performs a real GET against the OData service document. The connection is only created if the live test succeeds — failures are shown honestly.</div>
          <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
            <button onClick={runTest} disabled={busy || !form.secret || !form.base_url} style={{ ...btn, borderColor: '#c27847', color: '#c27847' }}>
              {busy ? <Loader2 className="animate-spin" size={13} /> : <PlugZap size={13} />} {busy ? 'Testing…' : 'Test connection'}
            </button>
            <button className="btn-primary" disabled={busy || !(testResult && testResult.success) || !!createResult} onClick={createAndDiscover} style={{ display: 'flex', alignItems: 'center', gap: '6px', opacity: (testResult && testResult.success) ? 1 : 0.5 }}>
              <CheckCircle2 size={14} /> Create &amp; discover schema
            </button>
          </div>
          {testResult && (
            <div style={{ marginTop: '12px', padding: '10px 12px', borderRadius: '8px', fontSize: '0.78rem', border: `1px solid ${testResult.success ? 'rgba(16,185,129,0.35)' : 'rgba(220,38,38,0.3)'}`, background: testResult.success ? 'rgba(16,185,129,0.07)' : 'rgba(220,38,38,0.06)', color: testResult.success ? '#059669' : '#dc2626' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '7px', fontWeight: 700 }}>
                {testResult.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {testResult.success ? 'Live test succeeded' : `Live test failed${testResult.error_category ? ` (${testResult.error_category})` : ''}`}
              </div>
              <div style={{ marginTop: '5px', color: 'var(--text-secondary)', fontWeight: 400 }}>{String(testResult.message || '').slice(0, 300)}</div>
              {testResult.success && (
                <div style={{ marginTop: '5px', fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>
                  {testResult.entity_sets} entity set(s) advertised · {testResult.latency_ms} ms · auth: {JSON.stringify(testResult.auth)}
                </div>
              )}
            </div>
          )}
          {createResult && (
            <div style={{ marginTop: '12px', padding: '10px 12px', borderRadius: '8px', background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.24)', fontSize: '0.78rem', color: 'var(--teal-primary)' }}>
              <b>Connection “{createResult.connection.name}” created.</b>
              {createResult.discovery
                ? <div style={{ marginTop: '4px', color: 'var(--text-secondary)' }}>Schema discovered: {createResult.discovery.entity_count} entity set(s), {createResult.discovery.service_count} service(s). It now appears as a selectable data source.</div>
                : <div style={{ marginTop: '4px', color: '#dc2626' }}>Discovery failed after create — use “Refresh schema” on the connection card. ({String(createResult.discoveryError || '').slice(0, 200)})</div>}
            </div>
          )}
        </div>
      )}

      <ErrorLine msg={error} />

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '16px' }}>
        <button onClick={step === 1 ? onCancel : () => setStep(step - 1)} style={btn}>{step === 1 ? 'Cancel' : 'Back'}</button>
        {step < 4 ? (
          <button className="btn-primary" disabled={!stepValid(step)} onClick={() => { setStep(step + 1); if (step + 1 === 4) setTestResult(null); }}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', opacity: stepValid(step) ? 1 : 0.5 }}>
            Next <ArrowRight size={14} />
          </button>
        ) : (
          <button onClick={onCancel} style={btn}>Done — close wizard</button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Entity browser: cached metadata table + bounded, role-authorized preview
// ---------------------------------------------------------------------------

function SapEntityBrowser({ connId }) {
  const [entities, setEntities] = useState(null);
  const [openEntity, setOpenEntity] = useState(null);
  const [meta, setMeta] = useState({});        // entity -> metadata dict
  const [previewRole, setPreviewRole] = useState('executive');
  const [preview, setPreview] = useState({});  // entity -> result | {error}
  const [busy, setBusy] = useState({});

  const load = useCallback(async () => {
    setEntities(null);
    const r = await sapJson(`/api/v1/connections/${connId}/entities`);
    if (r.ok) setEntities(r.data.entities || []);
    else setEntities({ error: r.error });
  }, [connId]);

  const openMetadata = async (name) => {
    if (openEntity === name) { setOpenEntity(null); return; }
    setOpenEntity(name);
    if (meta[name]) return;
    const r = await sapJson(`/api/v1/connections/${connId}/entities/${encodeURIComponent(name)}/metadata`);
    if (r.ok) setMeta((m) => ({ ...m, [name]: r.data }));
    else setMeta((m) => ({ ...m, [name]: { error: r.error } }));
  };

  // Structured plan only — the LLM and the browser never emit URLs or SQL for SAP.
  const runPreview = async (name) => {
    const m = meta[name]; if (!m || !m.properties) return;
    setBusy((b) => ({ ...b, [name]: true }));
    setPreview((p) => ({ ...p, [name]: null }));
    const nonBinary = m.properties.filter((p2) => p2.json_type !== 'binary');
    const select = (m.keys && m.keys.length ? m.keys : [nonBinary[0]?.name].filter(Boolean))
      .concat(nonBinary.map((p2) => p2.name))
      .filter((v, i, a) => v && a.indexOf(v) === i)
      .slice(0, 12);
    const r = await sapJson(`/api/v1/connections/${connId}/entities/${encodeURIComponent(name)}/preview`, {
      method: 'POST',
      headers: { 'X-User-Role': previewRole },
      body: JSON.stringify({ select, top: 10 }),
    });
    setBusy((b) => ({ ...b, [name]: false }));
    setPreview((p) => ({ ...p, [name]: r.ok ? r.data : { error: r.error } }));
  };

  useEffect(() => { load(); }, [load]);

  if (!entities) {
    return <button onClick={load} style={{ ...btn, marginTop: '10px' }}><Loader2 className="animate-spin" size={13} /> Load entity browser</button>;
  }
  if (entities.error) return <ErrorLine msg={entities.error} />;

  return (
    <div style={{ marginTop: '12px', borderTop: '1px solid var(--border-card)', paddingTop: '10px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <b style={{ fontSize: '0.78rem', color: 'var(--text-primary)' }}><Boxes size={13} style={{ verticalAlign: -2, marginRight: 5 }} />Discovered entity sets ({entities.length})</b>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>preview as role:</span>
        <select value={previewRole} onChange={(e) => setPreviewRole(e.target.value)} style={{ padding: '3px 7px', borderRadius: '7px', border: '1px solid var(--border-card)', background: 'var(--bg-surface)', color: 'var(--text-primary)', fontSize: '0.72rem' }}>
          {SAP_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button onClick={load} style={{ ...btn, marginLeft: 'auto' }}><RefreshCw size={12} /> Reload</button>
      </div>
      {entities.map((e) => {
        const open = openEntity === e.name;
        const m = meta[e.name];
        const pv = preview[e.name];
        const isBinary = m?.properties?.some((p) => p.json_type === 'binary');
        return (
          <div key={e.name} style={{ border: '1px solid var(--border-card)', borderRadius: '8px', padding: '8px 10px', marginBottom: '7px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontFamily: 'monospace', fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)' }}>{e.name}</span>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>{e.field_count} field(s) · keys: {e.keys?.length ? e.keys.join(', ') : '—'}</span>
              {e.count != null && <span style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>· inlinecount {e.count}</span>}
              <button onClick={() => openMetadata(e.name)} style={{ ...btn, marginLeft: 'auto' }}>
                {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />} {open ? 'Hide' : 'Metadata & preview'}
              </button>
            </div>
            {open && (
              <div style={{ marginTop: '10px' }}>
                {!m && <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)' }}><Loader2 className="animate-spin" size={12} /> Reading cached metadata…</div>}
                {m?.error && <ErrorLine msg={m.error} />}
                {m && m.properties && (
                  <>
                    <div style={{ overflowX: 'auto', border: '1px solid var(--border-card)', borderRadius: '8px' }}>
                      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.7rem' }}>
                        <thead><tr style={{ background: 'rgba(120,120,120,0.06)' }}>
                          {['Field', 'OData type', 'Maps to', 'Key', 'Nullable', 'Read-only', 'Max len'].map((h) => <th key={h} style={{ textAlign: 'left', padding: '5px 8px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{h}</th>)}
                        </tr></thead>
                        <tbody>
                          {m.properties.slice(0, 60).map((p) => (
                            <tr key={p.name} style={{ borderTop: '1px solid var(--border-card)' }}>
                              <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--text-primary)' }}>{p.name}{p.description ? ` — ${String(p.description).slice(0, 60)}` : ''}</td>
                              <td style={{ padding: '4px 8px', color: 'var(--text-secondary)' }}>{p.odata_type}</td>
                              <td style={{ padding: '4px 8px', color: 'var(--text-tertiary)' }}>{p.json_type}</td>
                              <td style={{ padding: '4px 8px' }}>{p.is_key ? '🔑' : ''}</td>
                              <td style={{ padding: '4px 8px' }}>{p.nullable ? 'yes' : 'no'}</td>
                              <td style={{ padding: '4px 8px' }}>{p.readonly ? 'yes' : 'no'}</td>
                              <td style={{ padding: '4px 8px' }}>{p.max_length ?? ''}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {m.properties.length > 60 && <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', padding: '4px 8px' }}>Showing first 60 of {m.properties.length} declared properties.</div>}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                      <button onClick={() => runPreview(e.name)} disabled={busy[e.name]} style={btn}>
                        {busy[e.name] ? <Loader2 className="animate-spin" size={12} /> : <Eye size={12} />} Preview 10 rows (bounded, role: {previewRole})
                      </button>
                      {isBinary && <span style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)' }}>binary/stream fields are excluded from previews by policy</span>}
                    </div>
                    {pv && pv.error && <ErrorLine msg={pv.error} />}
                    {pv && pv.rows && (
                      <div style={{ marginTop: '10px' }}>
                        <div style={{ fontSize: '0.74rem', color: 'var(--text-primary)', marginBottom: '6px' }}>
                          <b>{pv.row_count}</b> row(s) returned in {pv.execution_time_ms} ms{pv.truncated ? ' · truncated at fetch limit' : ''}
                        </div>
                        <div style={{ overflowX: 'auto', border: '1px solid var(--border-card)', borderRadius: '8px' }}>
                          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.68rem' }}>
                            <thead><tr style={{ background: 'rgba(120,120,120,0.06)' }}>
                              {pv.columns.map((c) => <th key={c} style={{ textAlign: 'left', padding: '5px 8px', color: '#c27847', whiteSpace: 'nowrap' }}>{c}</th>)}
                            </tr></thead>
                            <tbody>
                              {pv.rows.map((row, i) => (
                                <tr key={i} style={{ borderTop: '1px solid var(--border-card)' }}>
                                  {pv.columns.map((c) => <td key={c} style={{ padding: '4px 8px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{row[c] == null ? '—' : String(row[c])}</td>)}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div style={{ marginTop: '6px', fontSize: '0.68rem', color: 'var(--text-tertiary)', display: 'flex', gap: '5px', alignItems: 'flex-start' }}>
                          <ShieldCheck size={11} style={{ flexShrink: 0, marginTop: 2 }} /> {pv.limitations}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Management card per SAP connection
// ---------------------------------------------------------------------------

function SapConnectionCard({ conn, onChanged }) {
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [showBrowser, setShowBrowser] = useState(false);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [newSecret, setNewSecret] = useState('');
  const lc = lifecycleStyle[conn.lifecycle_status] || lifecycleStyle.configured;

  const call = async (kind, url, opts) => {
    setBusy(kind); setError(null); setNote(null);
    const r = await sapJson(url, opts);
    setBusy('');
    if (!r.ok) { setError(r.error); return null; }
    return r.data;
  };

  const probeHealth = async () => {
    const d = await call('health', `/api/v1/connections/${conn.id}/health`);
    if (d) setNote(d.healthy
      ? `Healthy — ${d.last_check_message || 'service document OK'} (entities cached: ${d.entities_cached})`
      : `Degraded (${d.error_category || 'unknown'}): ${d.last_check_message || ''}`);
    onChanged();
  };

  const refreshSchema = async () => {
    const d = await call('refresh', `/api/v1/connections/${conn.id}/schema/refresh`, { method: 'POST' });
    if (d) setNote(`Discovered ${d.entity_count} entity set(s) / ${d.service_count} service(s). Changes: +${d.changes.added.length} −${d.changes.removed.length} =${d.changes.unchanged}${d.source_version ? ` · version: ${String(d.source_version).slice(0, 60)}` : ''}`);
    onChanged();
  };

  const disable = async () => {
    if (!window.confirm(`Disable SAP connection “${conn.name}”? QueryPilot will stop offering this source (soft-disable, audited).`)) return;
    const d = await call('disable', `/api/v1/connections/${conn.id}/disable`, { method: 'POST' });
    if (d) onChanged();
  };

  const rotate = async () => {
    if (!newSecret) { setError('Enter the new secret first.'); return; }
    const d = await call('rotate', `/api/v1/connections/${conn.id}`, { method: 'PATCH', body: JSON.stringify({ secret: newSecret }) });
    if (d) { setNote('Credential rotated (re-encrypted at rest; old ciphertext replaced).'); setRotateOpen(false); setNewSecret(''); }
  };

  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid rgba(194,120,71,0.35)', borderRadius: '12px', padding: '14px 16px', marginTop: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ width: 34, height: 34, borderRadius: '9px', background: 'rgba(194,120,71,0.14)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#c27847', flexShrink: 0 }}><PlugZap size={18} /></div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>
            {conn.name}
            <span style={{ marginLeft: '8px', fontSize: '0.62rem', padding: '2px 8px', borderRadius: '10px', background: lc.bg, color: lc.color, fontWeight: 700, verticalAlign: 'middle' }}>{lc.label}</span>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '2px', wordBreak: 'break-all' }}>
            {conn.base_url}{conn.service_path || ''} · OData v{conn.odata_version} · {conn.auth_mode === 'oauth_client_credentials' ? 'OAuth2 client credentials' : 'Basic'} · {conn.deployment_type?.replace('_', ' ')}
            {conn.secret_ref && conn.secret_ref !== 'credential-store' ? ` · cred ref: ${conn.secret_ref}` : ''}
          </div>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', marginTop: '1px' }}>
            metadata refreshed: {conn.metadata_refreshed_at ? new Date(conn.metadata_refreshed_at).toLocaleString() : 'never'} · last success: {conn.last_success_at ? new Date(conn.last_success_at).toLocaleString() : '—'} · TLS verify {conn.tls_verify ? 'on' : 'OFF'}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '7px', marginTop: '10px', flexWrap: 'wrap' }}>
        <button onClick={probeHealth} disabled={!!busy} style={btn}>{busy === 'health' ? <Loader2 className="animate-spin" size={12} /> : <PlugZap size={12} />} Health</button>
        <button onClick={refreshSchema} disabled={!!busy} style={btn}>{busy === 'refresh' ? <Loader2 className="animate-spin" size={12} /> : <RefreshCw size={12} />} Refresh schema</button>
        <button onClick={() => setShowBrowser((v) => !v)} style={btn}>{showBrowser ? <ChevronUp size={12} /> : <ChevronDown size={12} />} Entities</button>
        <button onClick={() => { setRotateOpen((v) => !v); setError(null); }} style={btn}><KeyRound size={12} /> Rotate credential</button>
        <button onClick={disable} disabled={!!busy} style={dangerBtn}>{busy === 'disable' ? <Loader2 className="animate-spin" size={12} /> : <Ban size={12} />} Disable</button>
      </div>

      {rotateOpen && (
        <div style={{ display: 'flex', gap: '8px', marginTop: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input type="password" autoComplete="new-password" placeholder="new secret (never displayed afterwards)" value={newSecret} onChange={(e) => setNewSecret(e.target.value)}
            style={{ ...inputStyle, width: 'auto', flex: 1, minWidth: 220, marginTop: 0 }} />
          <button onClick={rotate} disabled={busy === 'rotate'} style={btn}>{busy === 'rotate' ? <Loader2 className="animate-spin" size={12} /> : 'Save (re-encrypt)'}</button>
        </div>
      )}

      {note && (
        <div style={{ marginTop: '10px', fontSize: '0.76rem', color: 'var(--teal-primary)', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
          <CheckCircle2 size={13} style={{ flexShrink: 0, marginTop: 1 }} /> {String(note).slice(0, 400)}
        </div>
      )}
      <ErrorLine msg={error} />

      {showBrowser && <SapEntityBrowser connId={conn.id} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: list existing SAP connections + wizard entry point (executive only)
// ---------------------------------------------------------------------------

export default function SapConnectorPanel({ onSourcesChanged }) {
  const [conns, setConns] = useState(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    const r = await sapJson('/api/v1/connections');
    if (r.ok) setConns((r.data || []).filter((c) => c.connector_type === 'sap_s4hana' && c.is_active));
    else { setError(r.error); setConns([]); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const changed = () => { load(); if (onSourcesChanged) onSourcesChanged(); };

  return (
    <div style={{ margin: '20px 0 6px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <h2 style={{ fontSize: '0.95rem', margin: 0, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <PlugZap size={16} style={{ color: '#c27847' }} /> SAP S/4HANA Enterprise Connector (read-only OData)
        </h2>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>live endpoints — never mocked; results reflect real SAP responses</span>
        <button onClick={load} style={{ ...btn, marginLeft: 'auto' }}><RefreshCw size={12} /> Reload</button>
        <button className="btn-primary" onClick={() => setWizardOpen((v) => !v)} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Plus size={14} /> {wizardOpen ? 'Close wizard' : 'New SAP connection'}
        </button>
      </div>

      {error && <ErrorLine msg={error} />}

      {wizardOpen && (
        <SapWizard onDone={changed} onCancel={() => setWizardOpen(false)} />
      )}

      {conns && conns.length === 0 && !wizardOpen && (
        <div style={{ textAlign: 'center', padding: '22px', color: 'var(--text-secondary)', fontSize: '0.82rem', border: '1px dashed var(--border-card)', borderRadius: '12px', marginTop: '12px' }}>
          No SAP connections yet. Create one with the wizard — it performs a real connection test before anything is saved.
          <div style={{ marginTop: '8px', fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>Reminder: the target host must already be listed in the server's SAP_ALLOWED_HOSTS (fail-closed).</div>
        </div>
      )}

      {conns && conns.map((c) => <SapConnectionCard key={c.id} conn={c} onChanged={changed} />)}
    </div>
  );
}
