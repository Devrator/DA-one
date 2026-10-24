import React, { useState, useEffect } from 'react';
import { Shield, ShieldAlert, User, ChevronDown, Check, Info } from 'lucide-react';

export default function RoleSelector({ currentRole, onRoleChange }) {
  const [isOpen, setIsOpen] = useState(false);
  const [matrixModalOpen, setMatrixModalOpen] = useState(false);
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

  const activePersona = personas.find(p => p.username === currentRole) || personas[0];

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
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: '8px' }}>
      {/* Active Persona Trigger */}
      <div 
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 12px',
          borderRadius: '10px',
          background: '#ffffff',
          border: '1px solid #e5dfd3',
          cursor: 'pointer',
          userSelect: 'none',
          transition: 'all 0.2s ease',
        }}
      >
        <div style={{
          width: '24px',
          height: '24px',
          borderRadius: '6px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          ...getRoleBadgeStyle(activePersona.role)
        }}>
          <User size={13} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: '10px', color: '#8090a7', textTransform: 'uppercase', letterSpacing: '0.05em', lineHeight: 1 }}>
            Security Persona
          </div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b', display: 'flex', alignItems: 'center', gap: '4px' }}>
            {activePersona.username}
            <ChevronDown size={12} color="#8090a7" />
          </div>
        </div>
      </div>

      {/* Permissions Matrix Button */}
      <button
        onClick={() => setMatrixModalOpen(true)}
        title="View 3-Role Permission Matrix"
        style={{
          padding: '6px 12px',
          borderRadius: '10px',
          background: '#ffffff',
          border: '1px solid #e5dfd3',
          color: '#475569',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '5px',
          fontSize: '12px',
          fontWeight: 600,
        }}
      >
        <Shield size={13} style={{ color: 'var(--teal-primary)' }} />
        <span>Matrix</span>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div 
          style={{
            position: 'absolute',
            top: '110%',
            right: 0,
            width: '340px',
            background: '#ffffff',
            border: '1px solid #e5dfd3',
            borderRadius: '12px',
            boxShadow: '0 16px 36px rgba(17, 94, 89, 0.12)',
            zIndex: 9999,
            padding: '8px',
          }}
        >
          <div style={{ padding: '8px 10px', borderBottom: '1px solid #f1ece4', marginBottom: '6px' }}>
            <div style={{ fontSize: '11px', color: '#115e59', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Switch Verified Identity (Server-Enforced)
            </div>
            <div style={{ fontSize: '11px', color: '#8090a7' }}>
              Permissions and PostgreSQL RLS resolve server-side.
            </div>
          </div>
          {personas.map((p) => {
            const isSelected = p.username === currentRole;
            return (
              <div
                key={p.username}
                onClick={() => {
                  onRoleChange(p.username);
                  setIsOpen(false);
                }}
                style={{
                  padding: '9px 12px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  background: isSelected ? 'rgba(17, 94, 89, 0.08)' : 'transparent',
                  border: isSelected ? '1px solid rgba(17, 94, 89, 0.25)' : '1px solid transparent',
                  marginBottom: '3px',
                  transition: 'background 0.15s ease',
                }}
              >
                <div style={{
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  marginTop: '2px',
                  ...getRoleBadgeStyle(p.role)
                }}>
                  {p.role.replace('_', ' ')}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12px', fontWeight: 700, color: '#0f172a' }}>
                    {p.username}
                  </div>
                  <div style={{ fontSize: '11px', color: '#64748b', lineHeight: 1.3 }}>
                    {p.description}
                  </div>
                </div>
                {isSelected && <Check size={14} color="#115e59" style={{ marginTop: '4px' }} />}
              </div>
            );
          })}
        </div>
      )}

      {/* Permission Matrix Modal */}
      {matrixModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.8)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 10000,
        }}>
          <div style={{
            background: '#0d131f',
            border: '1px solid #334155',
            borderRadius: '12px',
            width: '720px',
            maxHeight: '85vh',
            overflowY: 'auto',
            padding: '24px',
            color: '#f8fafc',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.9)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Shield size={20} color="#38bdf8" />
                <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>Phase 2 Role Security Matrix</h3>
              </div>
              <button 
                onClick={() => setMatrixModalOpen(false)}
                style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '18px' }}
              >
                &times;
              </button>
            </div>

            <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '20px' }}>
              Identities are verified strictly on the server. Permissions are enforced at the database level using PostgreSQL Row-Level Security (RLS) on <code style={{ color: '#38bdf8' }}>sales.sales_orders</code>, <code style={{ color: '#38bdf8' }}>sales.customers</code>, and <code style={{ color: '#38bdf8' }}>sales.regional_targets</code> with AST column pruning and dedicated read-only credentials.
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
              <thead>
                <tr style={{ background: '#1e293b', borderBottom: '1px solid #334155' }}>
                  <th style={{ padding: '10px', textAlign: 'left' }}>Role</th>
                  <th style={{ padding: '10px', textAlign: 'left' }}>PostgreSQL RLS Scope</th>
                  <th style={{ padding: '10px', textAlign: 'left' }}>Restricted Columns</th>
                  <th style={{ padding: '10px', textAlign: 'left' }}>Prohibited Tables</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
                  <td style={{ padding: '10px', fontWeight: 600, color: '#38bdf8' }}>Executive (Admin)</td>
                  <td style={{ padding: '10px', color: '#cbd5e1' }}>Unrestricted organization-wide access</td>
                  <td style={{ padding: '10px', color: '#10b981' }}>None (Full visibility)</td>
                  <td style={{ padding: '10px', color: '#10b981' }}>None</td>
                </tr>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
                  <td style={{ padding: '10px', fontWeight: 600, color: '#fbbf24' }}>Regional Manager</td>
                  <td style={{ padding: '10px', color: '#cbd5e1' }}>Restricted to assigned region (<code style={{ color: '#fbbf24' }}>region_id</code>)</td>
                  <td style={{ padding: '10px', color: '#f87171' }}>
                    customers.phone, customers.email, product_catalog.cost_price
                  </td>
                  <td style={{ padding: '10px', color: '#10b981' }}>None</td>
                </tr>
                <tr>
                  <td style={{ padding: '10px', fontWeight: 600, color: '#a78bfa' }}>Sales Representative</td>
                  <td style={{ padding: '10px', color: '#cbd5e1' }}>Restricted to own orders (<code style={{ color: '#a78bfa' }}>sales_rep</code>)</td>
                  <td style={{ padding: '10px', color: '#f87171' }}>
                    cost_price, phone, email, regional_targets.revenue_target, regions.manager_name
                  </td>
                  <td style={{ padding: '10px', color: '#f87171' }}>
                    sales.regional_targets
                  </td>
                </tr>
              </tbody>
            </table>

            <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setMatrixModalOpen(false)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '6px',
                  background: '#38bdf8',
                  color: '#0f172a',
                  fontWeight: 600,
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Close Matrix
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
