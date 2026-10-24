import React, { useState } from 'react';
import { Shield, Sparkles, Lock, Mail, ArrowRight, CheckCircle2, Database, Cpu, Server, Check, Sun, Moon } from 'lucide-react';
import DaOneLogo from './DaOneLogo';

export default function LoginScreen({ onLogin, initialRole = 'executive', theme = 'light', onToggleTheme }) {
  const [selectedRole, setSelectedRole] = useState(initialRole);
  const [email, setEmail] = useState('deepak.sharma@da-one.ai');
  const [password, setPassword] = useState('••••••••••••');
  const [remember, setRemember] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  const ROLES = [
    {
      id: 'executive',
      name: 'Executive',
      desc: 'Unrestricted full access across all 5 sales regions and unmasked customer PII.',
      badge: 'Full Access'
    },
    {
      id: 'regional_manager_north',
      name: 'Regional Manager (North)',
      desc: 'Row-level security scoped strictly to North region records and targets.',
      badge: 'RLS Filtered'
    },
    {
      id: 'sales_rep_carol',
      name: 'Sales Rep (Carol Chen)',
      desc: 'Granular field filtering scoped strictly to Representative ID 103 orders.',
      badge: 'Rep Scoped'
    }
  ];

  const handleSubmit = (e) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      onLogin({
        name: 'Deepak Sharma',
        email,
        role: selectedRole
      });
    }, 600);
  };

  const handleQuickRole = (roleId) => {
    setSelectedRole(roleId);
    if (roleId === 'sales_rep_carol') {
      setEmail('carol.chen@da-one.ai');
    } else if (roleId === 'regional_manager_north') {
      setEmail('north.manager@da-one.ai');
    } else {
      setEmail('deepak.sharma@da-one.ai');
    }
  };

  const PARTICLES = Array.from({ length: 16 }, (_, i) => ({
    id: i,
    left: `${(i * 6.3 + 3) % 100}%`,
    size: `${4 + (i % 4) * 2}px`,
    delay: `${(i * 1.4) % 12}s`,
    dur: `${13 + (i % 5) * 2.5}s`,
    hue: ['teal', 'mint', 'copper'][i % 3],
  }));

  return (
    <div className="da-login-screen">
      {/* Project-themed animated scene: flowing brand ribbons + rising data particles */}
      <div className="da-login-scene" aria-hidden="true">
        <div className="da-login-ribbons">
          <svg className="da-login-ribbon ribbon-1" viewBox="0 0 1440 320" preserveAspectRatio="none">
            <defs>
              <linearGradient id="ribTeal" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#115e59" stopOpacity="0" />
                <stop offset="35%" stopColor="#14b8a6" stopOpacity="0.55" />
                <stop offset="70%" stopColor="#0b3b3c" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0,160 C240,110 480,220 720,160 C960,100 1200,220 1440,150 L1440,214 C1200,284 960,164 720,224 C480,284 240,174 0,224 Z" fill="url(#ribTeal)" />
            <path className="rib-flow" d="M0,187 C240,140 480,252 720,192 C960,132 1200,252 1440,182" />
          </svg>
          <svg className="da-login-ribbon ribbon-2" viewBox="0 0 1440 320" preserveAspectRatio="none">
            <defs>
              <linearGradient id="ribCopper" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#c27847" stopOpacity="0" />
                <stop offset="40%" stopColor="#e08343" stopOpacity="0.5" />
                <stop offset="75%" stopColor="#8c4524" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#c27847" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0,170 C260,220 520,110 780,170 C1040,230 1240,120 1440,170 L1440,232 C1240,182 1040,292 780,232 C520,172 260,282 0,232 Z" fill="url(#ribCopper)" />
            <path className="rib-flow" d="M0,201 C260,251 520,141 780,201 C1040,261 1240,151 1440,201" />
          </svg>
          <svg className="da-login-ribbon ribbon-3" viewBox="0 0 1440 320" preserveAspectRatio="none">
            <defs>
              <linearGradient id="ribMint" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0" />
                <stop offset="50%" stopColor="#14b8a6" stopOpacity="0.45" />
                <stop offset="100%" stopColor="#0d9488" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0,150 C300,210 600,110 900,170 C1100,210 1300,140 1440,175 L1440,225 C1300,190 1100,260 900,220 C600,160 300,260 0,200 Z" fill="url(#ribMint)" />
            <path className="rib-flow" d="M0,175 C300,235 600,135 900,195 C1100,235 1300,165 1440,200" />
          </svg>
        </div>
        <div className="da-login-particles">
          {PARTICLES.map((p) => (
            <span
              key={p.id}
              className={`da-login-particle p-${p.hue}`}
              style={{ left: p.left, width: p.size, height: p.size, animationDelay: p.delay, animationDuration: p.dur }}
            />
          ))}
        </div>
      </div>

      {/* Centered Login Tile */}
      <div className="da-login-card" style={{ position: 'relative', zIndex: 1 }}>
        {/* Floating Theme Switcher */}
        {onToggleTheme && (
          <button
            onClick={onToggleTheme}
            className="da-top-icon-btn"
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              width: '32px',
              height: '32px',
              borderRadius: '8px'
            }}
            title={theme === 'dark' ? 'Switch to Bright Mode' : 'Switch to Dark Mode'}
          >
            {theme === 'dark' ? (
              <Sun size={14} style={{ color: '#f59e0b' }} />
            ) : (
              <Moon size={14} style={{ color: 'var(--copper-primary)' }} />
            )}
          </button>
        )}

        {/* Top Brand & Emblem Header */}
        <div className="da-login-header">
          <div className="da-login-emblem" style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px' }}>
            <DaOneLogo height={48} animated={true} />
          </div>
          <div className="da-login-badge">
            <span className="status-dot" />
            <span>Autonomous Database Analytics Agent</span>
          </div>
          <h2 className="da-login-title">Executive Sign In</h2>
          <p className="da-login-subtitle">
            Access multi-turn natural language SQL synthesis, verified benchmarks, and grounded business insights.
          </p>
        </div>

        {/* Security Role Selector */}
        <div className="da-login-role-section">
          <div className="da-login-section-label">Select RBAC Persona</div>
          <div className="da-login-role-grid">
            {ROLES.map((r) => {
              const active = selectedRole === r.id;
              return (
                <div
                  key={r.id}
                  className={`da-login-role-tile ${active ? 'active' : ''}`}
                  onClick={() => handleQuickRole(r.id)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span className="da-login-role-name">{r.name}</span>
                    <span className={`da-login-role-badge ${active ? 'active' : ''}`}>
                      {r.badge}
                    </span>
                  </div>
                  <div className="da-login-role-desc">{r.desc}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="da-login-form">
          <div className="da-login-field">
            <label className="da-login-label">Analyst Email</label>
            <div className="da-login-input-wrap">
              <Mail size={16} className="da-login-input-icon" />
              <input
                type="email"
                className="da-login-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="da-login-field">
            <label className="da-login-label">Access Credentials</label>
            <div className="da-login-input-wrap">
              <Lock size={16} className="da-login-input-icon" />
              <input
                type="password"
                className="da-login-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.78rem', marginTop: '-2px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                style={{ accentColor: 'var(--teal-primary)' }}
              />
              <span>Keep session persistent</span>
            </label>
            <span style={{ color: 'var(--copper-primary)', fontWeight: 600, cursor: 'pointer' }}>
              Auto-authenticated demo
            </span>
          </div>

          <button type="submit" className="da-btn-login" disabled={isLoading}>
            {isLoading ? (
              <span>Authenticating...</span>
            ) : (
              <>
                <span>Enter Workspace</span>
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </form>

        {/* Trust Badges Footer */}
        <div className="da-login-footer">
          <div className="da-login-trust-item" title="PostgreSQL target DB with readonly enforcement">
            <Server size={13} style={{ color: 'var(--teal-primary)' }} />
            <span>PostgreSQL: 5433</span>
          </div>
          <div className="da-login-trust-item" title="Local open-weight model on Ollama">
            <Cpu size={13} style={{ color: 'var(--copper-primary)' }} />
            <span>qwen2.5-coder:7b</span>
          </div>
          <div className="da-login-trust-item" title="SQLGlot AST-based policy engine">
            <Shield size={13} style={{ color: 'var(--teal-primary)' }} />
            <span>100% AST Safety</span>
          </div>
        </div>
      </div>
    </div>
  );
}
