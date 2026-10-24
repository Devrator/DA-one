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

  return (
    <div className="da-login-screen">
      {/* Centered Login Tile */}
      <div className="da-login-card" style={{ position: 'relative' }}>
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
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '8px' }}>
            <DaOneLogo height={44} animated={true} />
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
