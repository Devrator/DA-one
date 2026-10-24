import React, { useState, useEffect } from 'react';
import { Shield, Clock, FileText, RefreshCw, AlertCircle, CheckCircle2 } from 'lucide-react';

export default function AuditLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/audit?limit=50');
      if (res.ok) {
        const data = await res.json();
        setLogs(data);
      }
    } catch (e) {
      console.error('Failed to load audit logs', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff' }}>
            Security & Execution Audit Trail
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Immutable chronological record of query submissions, AST validations, policy checks, and database interactions.
          </p>
        </div>

        <button className="btn-icon" onClick={fetchLogs} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh Audit Trail
        </button>
      </div>

      <div className="data-table-card">
        <div className="table-wrapper">
          <table className="styled-table">
            <thead>
              <tr>
                <th style={{ width: '180px' }}>Timestamp</th>
                <th>Event Type</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    Loading audit trail...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    No audit records recorded yet.
                  </td>
                </tr>
              ) : (
                logs.map((log, idx) => (
                  <tr key={idx}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td>
                      <span style={{
                        fontSize: '0.72rem',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: log.event_type.includes('error') || log.event_type.includes('reject')
                          ? 'var(--danger-bg)'
                          : 'rgba(99, 102, 241, 0.15)',
                        color: log.event_type.includes('error') || log.event_type.includes('reject')
                          ? 'var(--danger)'
                          : '#a5b4fc',
                        fontWeight: 500
                      }}>
                        {log.event_type}
                      </span>
                    </td>
                    <td style={{ fontWeight: 500, fontSize: '0.82rem' }}>
                      {log.action}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      {log.resource_type ? `${log.resource_type}:${log.resource_id?.slice(0, 8) || ''}` : '—'}
                    </td>
                    <td style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                      {log.details ? JSON.stringify(log.details) : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
