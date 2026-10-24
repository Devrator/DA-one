import React, { useState, useEffect } from 'react';
import { 
  Settings, Database, Cpu, Shield, Key, RefreshCw, 
  CheckCircle2, AlertCircle, Save, Moon, Sun, Lock, Server, Check, ShieldCheck
} from 'lucide-react';
import PageHeader from './PageHeader';

export default function SettingsView({ currentRole, onRoleChange, theme, onToggleTheme }) {
  // Target PostgreSQL connection (loaded live from backend runtime settings)
  const [dbHost, setDbHost] = useState('');
  const [dbPort, setDbPort] = useState('');
  const [dbName, setDbName] = useState('');
  const [dbUser, setDbUser] = useState('');
  const [dbPassword, setDbPassword] = useState('');
  const [dbSchema, setDbSchema] = useState('sales');
  const [statementTimeout, setStatementTimeout] = useState('30');

  // LLM runtime
  const [modelUrl, setModelUrl] = useState('');
  const [modelName, setModelName] = useState('');
  const [temperature, setTemperature] = useState('0.1');

  const [loadingConfig, setLoadingConfig] = useState(true);
  const [configError, setConfigError] = useState(null);

  const [testingDb, setTestingDb] = useState(false);
  const [dbTestResult, setDbTestResult] = useState(null);
  const [applyingDb, setApplyingDb] = useState(false);

  const [testingModel, setTestingModel] = useState(false);
  const [modelTestResult, setModelTestResult] = useState(null);
  const [applyingModel, setApplyingModel] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/v1/settings/runtime');
        if (!res.ok) throw new Error(`Settings endpoint returned ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setDbHost(data.target_db.host);
        setDbPort(String(data.target_db.port));
        setDbName(data.target_db.database_name);
        setDbUser(data.target_db.username);
        setDbSchema(data.target_db.schema_name || 'sales');
        setStatementTimeout(String(Math.round((data.target_db.statement_timeout_ms || 30000) / 1000)));
        setModelUrl(data.llm.base_url);
        setModelName(data.llm.model);
        setTemperature(String(data.llm.temperature));
        setConfigError(null);
      } catch (e) {
        if (!cancelled) setConfigError(`Could not load live runtime configuration: ${e.message}`);
      } finally {
        if (!cancelled) setLoadingConfig(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const dbPayload = () => ({
    host: dbHost.trim(),
    port: parseInt(dbPort, 10) || 5432,
    database_name: dbName.trim(),
    username: dbUser.trim(),
    password: dbPassword,
    schema_name: dbSchema.trim() || 'sales',
    statement_timeout_ms: (parseInt(statementTimeout, 10) || 30) * 1000,
  });

  const handleTestDb = async () => {
    setTestingDb(true);
    setDbTestResult(null);
    try {
      const res = await fetch('/api/v1/settings/target-db/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dbPayload()),
      });
      const data = await res.json();
      setDbTestResult({ success: data.success, message: data.message });
    } catch (e) {
      setDbTestResult({ success: false, message: `Test request failed: ${e.message}` });
    } finally {
      setTestingDb(false);
    }
  };

  const handleApplyDb = async () => {
    setApplyingDb(true);
    setDbTestResult(null);
    try {
      const res = await fetch('/api/v1/settings/target-db/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dbPayload()),
      });
      const data = await res.json();
      setDbTestResult({ success: data.success, message: data.message });
      if (data.success) setDbPassword('');
    } catch (e) {
      setDbTestResult({ success: false, message: `Apply request failed: ${e.message}` });
    } finally {
      setApplyingDb(false);
    }
  };

  const handleTestModel = async () => {
    setTestingModel(true);
    setModelTestResult(null);
    try {
      const res = await fetch('/api/v1/settings/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelName.trim(), base_url: modelUrl.trim() }),
      });
      const data = await res.json();
      setModelTestResult({ success: data.success, message: data.message });
    } catch (e) {
      setModelTestResult({ success: false, message: `Test request failed: ${e.message}` });
    } finally {
      setTestingModel(false);
    }
  };

  const handleApplyModel = async () => {
    setApplyingModel(true);
    setModelTestResult(null);
    try {
      const res = await fetch('/api/v1/settings/llm/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: modelName.trim(),
          base_url: modelUrl.trim(),
          temperature: parseFloat(temperature),
        }),
      });
      const data = await res.json();
      setModelTestResult({ success: data.success, message: data.message });
    } catch (e) {
      setModelTestResult({ success: false, message: `Apply request failed: ${e.message}` });
    } finally {
      setApplyingModel(false);
    }
  };

  const renderTestBanner = (result) => result && (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: '8px',
      fontSize: '0.78rem',
      padding: '8px 12px',
      borderRadius: '8px',
      background: result.success ? 'var(--success-bg)' : 'var(--danger-bg)',
      color: result.success ? 'var(--success)' : 'var(--danger)',
      border: `1px solid ${result.success ? 'var(--success-border)' : 'var(--danger-border)'}`
    }}>
      {result.success ? <CheckCircle2 size={15} style={{ marginTop: 1, flexShrink: 0 }} /> : <AlertCircle size={15} style={{ marginTop: 1, flexShrink: 0 }} />}
      <span>{result.message}</span>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1320px', margin: '0 auto' }}>
      {/* Executive Page Header */}
      <PageHeader
        icon={Settings}
        title="System & Security Settings"
        subtitle="Configure the live PostgreSQL target database, Ollama LLM runtime, and anti-hallucination guardrails. All changes are verified against the real servers before being applied."
        badge="System Administration"
        badgeType="teal"
      />

      {loadingConfig && (
        <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <RefreshCw size={14} className="animate-spin" />
          Loading live runtime configuration from backend…
        </div>
      )}
      {configError && (
        <div style={{
          background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: '12px',
          padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '10px',
          color: 'var(--danger)', fontSize: '0.86rem', fontWeight: 600
        }}>
          <AlertCircle size={18} />
          <span>{configError}</span>
        </div>
      )}

      {/* Settings Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '1.25rem' }}>

        {/* Panel 1: Target PostgreSQL Database */}
        <div className="da-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Server size={18} style={{ color: 'var(--teal-primary)' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)', margin: 0 }}>
                Target Database Connection
              </h3>
            </div>
            <span className="da-pill da-pill-turns">PostgreSQL</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '10px' }}>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Host</label>
              <input type="text" className="da-login-input" value={dbHost} onChange={(e) => setDbHost(e.target.value)} />
            </div>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Port</label>
              <input type="text" className="da-login-input" value={dbPort} onChange={(e) => setDbPort(e.target.value)} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '10px' }}>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Database Name</label>
              <input type="text" className="da-login-input" value={dbName} onChange={(e) => setDbName(e.target.value)} />
            </div>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Schema</label>
              <input type="text" className="da-login-input" value={dbSchema} onChange={(e) => setDbSchema(e.target.value)} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Username (read-only role)</label>
              <input type="text" className="da-login-input" value={dbUser} onChange={(e) => setDbUser(e.target.value)} autoComplete="off" />
            </div>
            <div>
              <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Password</label>
              <input type="password" className="da-login-input" value={dbPassword} onChange={(e) => setDbPassword(e.target.value)} placeholder={dbPassword ? '' : '••••••••'} autoComplete="new-password" />
            </div>
          </div>

          <div>
            <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Statement Timeout (s)</label>
            <input type="number" className="da-login-input" value={statementTimeout} onChange={(e) => setStatementTimeout(e.target.value)} style={{ maxWidth: '140px' }} />
          </div>

          {renderTestBanner(dbTestResult)}

          <div style={{ marginTop: 'auto', paddingTop: '10px', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button className="btn-secondary" onClick={handleTestDb} disabled={testingDb || applyingDb || loadingConfig}>
              <RefreshCw size={13} className={testingDb ? 'animate-spin' : ''} />
              <span>{testingDb ? 'Testing…' : 'Test Connection'}</span>
            </button>
            <button className="btn-primary" onClick={handleApplyDb} disabled={applyingDb || testingDb || loadingConfig}>
              {applyingDb ? <RefreshCw size={13} className="animate-spin" /> : <Database size={13} />}
              <span>{applyingDb ? 'Applying…' : 'Apply & Use This Database'}</span>
            </button>
          </div>
        </div>

        {/* Panel 2: LLM Runtime & Inference */}
        <div className="da-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Cpu size={18} style={{ color: 'var(--copper-primary)' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)', margin: 0 }}>
                LLM Inference Engine
              </h3>
            </div>
            <span className="da-pill da-pill-session">Ollama Local</span>
          </div>

          <div>
            <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Ollama Base URL</label>
            <input type="text" className="da-login-input" value={modelUrl} onChange={(e) => setModelUrl(e.target.value)} />
          </div>

          <div>
            <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Model Tag</label>
            <input type="text" className="da-login-input" value={modelName} onChange={(e) => setModelName(e.target.value)} />
          </div>

          <div>
            <label className="da-login-label" style={{ marginBottom: '4px', display: 'block' }}>Sampling Temperature (0 = most deterministic)</label>
            <input type="text" className="da-login-input" value={temperature} onChange={(e) => setTemperature(e.target.value)} style={{ maxWidth: '140px' }} />
          </div>

          {renderTestBanner(modelTestResult)}

          <div style={{ marginTop: 'auto', paddingTop: '10px', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button className="btn-secondary" onClick={handleTestModel} disabled={testingModel || applyingModel || loadingConfig}>
              <RefreshCw size={13} className={testingModel ? 'animate-spin' : ''} />
              <span>{testingModel ? 'Verifying…' : 'Verify Model Health'}</span>
            </button>
            <button className="btn-primary" onClick={handleApplyModel} disabled={applyingModel || testingModel || loadingConfig}>
              {applyingModel ? <RefreshCw size={13} className="animate-spin" /> : <Check size={13} />}
              <span>{applyingModel ? 'Applying…' : 'Apply Model'}</span>
            </button>
          </div>
        </div>

        {/* Panel 3: Anti-Hallucination & Truth Guardrails (always enforced) */}
        <div className="da-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Shield size={18} style={{ color: 'var(--teal-primary)' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)', margin: 0 }}>
                Truth & Anti-Hallucination Guardrails
              </h3>
            </div>
            <span className="da-pill da-pill-turns">Always Enforced</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {[
              {
                title: 'Live Schema Grounding Gate',
                desc: 'Every generated SQL is checked against the real PostgreSQL schema. Hallucinated tables or columns are rejected and repaired before execution — the AI can never invent data objects.'
              },
              {
                title: 'Numeric Evidence Verification',
                desc: 'Every number in an AI explanation must trace to the actual query result (cell value, aggregate, or row count). Unverifiable claims are discarded and replaced with a deterministic summary.'
              },
              {
                title: 'Evidence Provenance on Every Answer',
                desc: 'Each answer shows a "Verified against PostgreSQL" badge with expandable proof: tables queried, rows returned, executed SQL, and verification outcomes.'
              },
              {
                title: 'Strict AST Read-Only Validation',
                desc: 'Blocks DROP, TRUNCATE, ALTER, INSERT, UPDATE, GRANT statements prior to execution. Connections authenticate with dedicated read-only credentials.'
              },
              {
                title: 'Row-Level Security & PII Masking',
                desc: 'PostgreSQL RLS scopes rows per persona; phone and email columns are pruned for non-executive roles before DB submission.'
              }
            ].map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border-card)'
                }}
              >
                <ShieldCheck size={16} style={{ color: 'var(--success)', marginTop: 2, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-headings)' }}>{item.title}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Panel 4: UI Appearance & Preferences */}
        <div className="da-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sun size={18} style={{ color: 'var(--copper-primary)' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)', margin: 0 }}>
                Theme & Interface Preferences
              </h3>
            </div>
            <span className="da-pill da-pill-session">
              {theme === 'dark' ? 'Obsidian Glass' : 'Alabaster Glass'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', borderRadius: '10px', background: 'var(--bg-secondary)', border: '1px solid var(--border-card)' }}>
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-headings)' }}>Executive Color Theme</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {theme === 'dark' ? 'Dark Obsidian Theme Active' : 'Bright Warm Alabaster Theme Active'}
              </div>
            </div>
            <button className="btn-secondary" onClick={onToggleTheme}>
              {theme === 'dark' ? <Sun size={14} style={{ color: '#f59e0b' }} /> : <Moon size={14} style={{ color: 'var(--copper-primary)' }} />}
              <span>{theme === 'dark' ? 'Switch to Bright' : 'Switch to Dark'}</span>
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '8px' }}>
            <div>• Active Persona: <strong>{currentRole}</strong></div>
            <div>• Local Storage Persistence: <strong>Enabled (da_one_theme)</strong></div>
            <div>• Runtime Config: <strong>Loaded live from /api/v1/settings/runtime</strong></div>
            <div>• Settings Persistence: <strong>Written to .env on apply</strong></div>
          </div>
        </div>

      </div>
    </div>
  );
}
