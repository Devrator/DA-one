import React, { useState, useEffect } from 'react';
import { Shield, User, Check } from 'lucide-react';

export default function RoleSelector({ currentRole, onRoleChange }) {
  const [rolesData, setRolesData] = useState(null);

  useEffect(() => {
    fetch('/api/v1/roles')
      .then(res => res.json())
      .then(data => setRolesData(data))
      .catch(err => console.warn('Could not load roles matrix', err));
  }, []);

  const personas = rolesData?.verified_personas || [
    { username: 'executive', role: 'executive', description: 'Executive / Admin — Unrestricted analytical visibility' },
    { username: 'regional_manager_north', role: 'regional_manager', description: 'Regional Manager (North) — Region 1 RLS only; PII & Cost restricted' },
    { username: 'regional_manager_south', role: 'regional_manager', description: 'Regional Manager (South) — Region 2 RLS only; PII & Cost restricted' },
    { username: 'sales_rep_carol', role: 'sales_rep', description: 'Sales Rep (Carol Chen) — Orders scoped to Carol Chen; Targets & Cost restricted' },
    { username: 'sales_rep_david', role: 'sales_rep', description: 'Sales Rep (David Kim) — Orders scoped to David Kim; Targets & Cost restricted' },
  ];

  const getRoleBadgeStyle = (role) => {
    switch (role) {
      case 'executive':
        return { background: 'rgba(17, 94, 89, 0.1)', border: '1px solid rgba(17, 94, 89, 0.3)', color: '#115e59' };
      case 'regional_manager':
        return { background: 'rgba(194, 120, 71, 0.12)', border: '1px solid rgba(194, 120, 71, 0.3)', color: '#c27847' };
      case 'sales_rep':
        return { background: 'rgba(13, 148, 136, 0.12)', border: '1px solid rgba(13, 148, 136, 0.3)', color: '#0d9488' };
      default:
        return { background: 'rgba(148, 163, 184, 0.15)', border: '1px solid rgba(148, 163, 184, 0.4)', color: '#64748b' };
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* ============================================================
          Section 1: Verified identity switcher (rendered inline so the
          modal's own scroll handles overflow — no clipped dropdown)
          ============================================================ */}
      <section>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
          <div style={{
            width: '30px', height: '30px', borderRadius: '8px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(17, 94, 89, 0.1)', border: '1px solid rgba(17, 94, 89, 0.25)',
          }}>
            <User size={15} style={{ color: '#115e59' }} />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: '#115e59', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Switch Verified Identity (Server-Enforced)
            </div>
            <div style={{ fontSize: '11px', color: '#8090a7' }}>
              Permissions and PostgreSQL RLS resolve server-side.
            </div>
          </div>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
          gap: '8px',
          marginTop: '12px',
        }}>
          {personas.map((p) => {
            const isSelected = p.username === currentRole;
            return (
              <div
                key={p.username}
                onClick={() => onRoleChange(p.username)}
                style={{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  background: isSelected ? 'rgba(17, 94, 89, 0.08)' : 'var(--bg-surface)',
                  border: isSelected ? '1px solid rgba(17, 94, 89, 0.35)' : '1px solid var(--border-card)',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{
                  padding: '2px 6px',
                  borderRadius: '5px',
                  fontSize: '9px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                  marginTop: '2px',
                  ...getRoleBadgeStyle(p.role),
                }}>
                  {p.role.replace('_', ' ')}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-headings)' }}>
                    {p.username}
                  </div>
                  <div style={{ fontSize: '11px', color: '#64748b', lineHeight: 1.3 }}>
                    {p.description}
                  </div>
                </div>
                {isSelected && <Check size={15} color="#115e59" style={{ marginTop: '3px', flexShrink: 0 }} />}
              </div>
            );
          })}
        </div>
      </section>

      {/* ============================================================
          Section 2: Phase 2 role security matrix (inline table, was
          previously a nested modal)
          ============================================================ */}
      <section>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <Shield size={18} style={{ color: 'var(--teal-primary)' }} />
          <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--text-headings)' }}>
            Phase 2 Role Security Matrix
          </h3>
        </div>

        <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '14px', lineHeight: 1.5 }}>
          Identities are verified strictly on the server. Permissions are enforced at the database level using
          PostgreSQL Row-Level Security (RLS) on <code style={{ color: '#0d9488' }}>sales.sales_orders</code>,{' '}
          <code style={{ color: '#0d9488' }}>sales.customers</code>, and{' '}
          <code style={{ color: '#0d9488' }}>sales.regional_targets</code> with AST column pruning and dedicated
          read-only credentials.
        </div>

        <div style={{ overflowX: 'auto', borderRadius: '10px', border: '1px solid var(--border-card)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '560px' }}>
            <thead>
              <tr style={{ background: 'var(--bg-secondary)' }}>
                <th style={{ padding: '10px', textAlign: 'left', color: 'var(--text-headings)', borderBottom: '1px solid var(--border-card)' }}>Role</th>
                <th style={{ padding: '10px', textAlign: 'left', color: 'var(--text-headings)', borderBottom: '1px solid var(--border-card)' }}>PostgreSQL RLS Scope</th>
                <th style={{ padding: '10px', textAlign: 'left', color: 'var(--text-headings)', borderBottom: '1px solid var(--border-card)' }}>Restricted Columns</th>
                <th style={{ padding: '10px', textAlign: 'left', color: 'var(--text-headings)', borderBottom: '1px solid var(--border-card)' }}>Prohibited Tables</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '10px', fontWeight: 600, color: '#115e59' }}>Executive (Admin)</td>
                <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>Unrestricted organization-wide access</td>
                <td style={{ padding: '10px', color: '#10b981' }}>None (Full visibility)</td>
                <td style={{ padding: '10px', color: '#10b981' }}>None</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '10px', fontWeight: 600, color: '#c27847' }}>Regional Manager</td>
                <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>Restricted to assigned region (<code style={{ color: '#c27847' }}>region_id</code>)</td>
                <td style={{ padding: '10px', color: '#b91c1c' }}>
                  customers.phone, customers.email, product_catalog.cost_price
                </td>
                <td style={{ padding: '10px', color: '#10b981' }}>None</td>
              </tr>
              <tr>
                <td style={{ padding: '10px', fontWeight: 600, color: '#7c3aed' }}>Sales Representative</td>
                <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>Restricted to own orders (<code style={{ color: '#7c3aed' }}>sales_rep</code>)</td>
                <td style={{ padding: '10px', color: '#b91c1c' }}>
                  cost_price, phone, email, regional_targets.revenue_target, regions.manager_name
                </td>
                <td style={{ padding: '10px', color: '#b91c1c' }}>
                  sales.regional_targets
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
