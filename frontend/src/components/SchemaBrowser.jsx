import React, { useState, useEffect } from 'react';
import { Database, Table, Key, Eye, Search, Layers, RefreshCw } from 'lucide-react';

export default function SchemaBrowser({ onSelectTableQuery }) {
  const [schemaData, setSchemaData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedTable, setSelectedTable] = useState(null);
  const [tablePreview, setTablePreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const fetchSchema = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/connections/default/schema');
      if (res.ok) {
        const data = await res.json();
        setSchemaData(data);
      }
    } catch (e) {
      console.error('Failed to load schema', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSchema();
  }, []);

  const handlePreviewTable = async (tableName) => {
    setSelectedTable(tableName);
    setPreviewLoading(true);
    try {
      const res = await fetch('/api/v1/queries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: `Show 10 sample records from sales.${tableName}`,
          connection_id: 'default'
        })
      });
      if (res.ok) {
        const data = await res.json();
        setTablePreview(data);
      }
    } catch (e) {
      console.error('Failed to preview table', e);
    } finally {
      setPreviewLoading(false);
    }
  };

  const tables = schemaData?.tables || [];
  const filteredTables = tables.filter(t => 
    t.table_name.toLowerCase().includes(search.toLowerCase()) ||
    t.columns.some(c => c.name.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: 'var(--text-headings)', fontWeight: 700 }}>Schema Catalog & Relations</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Target Database: <code style={{ color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)' }}>querypilot_target</code> (Schema: <code style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>sales</code>)
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={15} style={{ position: 'absolute', left: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Filter tables or columns..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '6px 12px 6px 32px',
                color: 'var(--text-primary)',
                fontSize: '0.85rem',
                outline: 'none',
              }}
            />
          </div>
          <button className="btn-icon" onClick={fetchSchema} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
          Loading database schema and catalog...
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '1.25rem' }}>
          {filteredTables.map((tbl, idx) => (
            <div key={idx} className="stat-card" style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Table size={18} style={{ color: 'var(--accent-primary)' }} />
                  <div>
                    <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-headings)' }}>{tbl.table_name}</h3>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      {tbl.row_count != null ? `${tbl.row_count.toLocaleString()} rows` : '0 rows'} • {tbl.columns.length} columns
                    </div>
                  </div>
                </div>

                <button 
                  className="btn-icon" 
                  onClick={() => handlePreviewTable(tbl.table_name)}
                  style={{ fontSize: '0.72rem' }}
                >
                  <Eye size={12} /> Preview
                </button>
              </div>

              {tbl.description && (
                <div style={{ fontSize: '0.78rem', color: '#94a3b8', marginBottom: '0.75rem', fontStyle: 'italic' }}>
                  "{tbl.description}"
                </div>
              )}

              {/* Columns list */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', marginTop: 'auto' }}>
                {tbl.columns.slice(0, 7).map((col, cIdx) => (
                  <div key={cIdx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.74rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      {col.is_primary_key && <span className="key-badge pk">PK</span>}
                      {col.foreign_key_to && <span className="key-badge fk">FK</span>}
                      <span style={{ fontFamily: 'var(--font-mono)', color: col.is_primary_key ? 'var(--teal-primary)' : 'var(--text-primary)' }}>{col.name}</span>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem', fontFamily: 'var(--font-mono)' }}>
                      {col.data_type}
                    </span>
                  </div>
                ))}
                {tbl.columns.length > 7 && (
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: '4px' }}>
                    +{tbl.columns.length - 7} more columns
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Preview Modal */}
      {selectedTable && (
        <div className="modal-overlay" onClick={() => setSelectedTable(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Table size={18} style={{ color: 'var(--teal-primary)' }} />
                <h3 style={{ fontSize: '1.1rem', color: 'var(--text-headings)', fontWeight: 700 }}>Data Preview: sales.{selectedTable}</h3>
              </div>
              <button className="btn-icon" onClick={() => setSelectedTable(null)}>✕</button>
            </div>
            <div className="modal-body">
              {previewLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                  Executing SELECT * FROM sales.{selectedTable} LIMIT 10...
                </div>
              ) : tablePreview?.result_data ? (
                <div className="table-wrapper">
                  <table className="styled-table">
                    <thead>
                      <tr>
                        {Object.keys(tablePreview.result_data[0] || {}).map((k, i) => (
                          <th key={i}>{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tablePreview.result_data.map((r, ri) => (
                        <tr key={ri}>
                          {Object.values(r).map((v, vi) => (
                            <td key={vi}>{v != null ? String(v) : 'null'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)' }}>No records found or preview failed.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
