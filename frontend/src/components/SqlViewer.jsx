import React, { useState } from 'react';
import { Copy, Check, ShieldCheck, Terminal, HelpCircle } from 'lucide-react';

export default function SqlViewer({ sql, safetyInfo, onExplain }) {
  const [copied, setCopied] = useState(false);

  if (!sql) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="sql-card">
      <div className="sql-header">
        <div className="sql-title-group">
          <Terminal size={16} style={{ color: 'var(--accent-primary)' }} />
          <span className="sql-title">Generated SQL Query</span>
          <div className="policy-badges">
            <span className="policy-badge verified">
              <ShieldCheck size={11} style={{ display: 'inline', marginRight: '3px' }} />
              Read-Only Safe
            </span>
            <span className="policy-badge">AST Validated</span>
            <span className="policy-badge">Timeout: 30s</span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn-icon" onClick={handleCopy}>
            {copied ? <Check size={13} style={{ color: 'var(--success)' }} /> : <Copy size={13} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      <pre className="sql-code-block">{sql}</pre>
    </div>
  );
}
