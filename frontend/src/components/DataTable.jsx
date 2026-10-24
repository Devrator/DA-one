import React, { useState, useMemo } from 'react';
import { Download, ChevronLeft, ChevronRight, ArrowUpDown, Search } from 'lucide-react';

export default function DataTable({ data, columns, totalRows }) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortCol, setSortCol] = useState(null);
  const [sortAsc, setSortAsc] = useState(true);

  if (!data || data.length === 0) return null;

  const colKeys = columns && columns.length > 0 
    ? columns.map(c => typeof c === 'string' ? c : c.name) 
    : Object.keys(data[0]);

  // Filtering
  const filteredData = useMemo(() => {
    if (!searchQuery.trim()) return data;
    const q = searchQuery.toLowerCase();
    return data.filter(row => 
      colKeys.some(k => String(row[k] ?? '').toLowerCase().includes(q))
    );
  }, [data, searchQuery, colKeys]);

  // Sorting
  const sortedData = useMemo(() => {
    if (!sortCol) return filteredData;
    return [...filteredData].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      if (va === vb) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      const na = parseFloat(va);
      const nb = parseFloat(vb);
      if (!isNaN(na) && !isNaN(nb)) {
        return sortAsc ? na - nb : nb - na;
      }
      return sortAsc 
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va));
    });
  }, [filteredData, sortCol, sortAsc]);

  // Pagination
  const totalPages = Math.ceil(sortedData.length / pageSize) || 1;
  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, currentPage, pageSize]);

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortAsc(!sortAsc);
    } else {
      setSortCol(col);
      setSortAsc(true);
    }
  };

  const handleExportCSV = () => {
    const header = colKeys.join(',');
    const rows = sortedData.map(row => 
      colKeys.map(k => {
        const val = row[k] == null ? '' : String(row[k]);
        return `"${val.replace(/"/g, '""')}"`;
      }).join(',')
    );
    const csvContent = "data:text/csv;charset=utf-8," + [header, ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `querypilot_export_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="data-table-card">
      <div className="table-controls">
        <div className="table-stats">
          <span><strong>{sortedData.length}</strong> rows {sortedData.length !== data.length ? `(filtered from ${data.length})` : ''}</span>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={14} style={{ position: 'absolute', left: '8px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Search table..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
              style={{
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px 4px 26px',
                color: 'var(--text-primary)',
                fontSize: '0.78rem',
                outline: 'none',
              }}
            />
          </div>
        </div>

        <button className="btn-icon" onClick={handleExportCSV}>
          <Download size={14} />
          Export CSV
        </button>
      </div>

      <div className="table-wrapper">
        <table className="styled-table">
          <thead>
            <tr>
              {colKeys.map((col, idx) => (
                <th key={idx} onClick={() => handleSort(col)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>{col}</span>
                    <ArrowUpDown size={12} style={{ opacity: sortCol === col ? 1 : 0.4, color: sortCol === col ? 'var(--accent-primary)' : 'inherit' }} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedData.map((row, rIdx) => (
              <tr key={rIdx}>
                {colKeys.map((col, cIdx) => {
                  const val = row[col];
                  const isNum = !isNaN(parseFloat(val)) && typeof val !== 'boolean';
                  return (
                    <td key={cIdx} style={{ fontFamily: isNum ? 'var(--font-mono)' : 'inherit' }}>
                      {val === null || val === undefined ? (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>null</span>
                      ) : isNum && String(val).includes('.') ? (
                        parseFloat(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                      ) : (
                        String(val)
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '0.75rem 1.25rem',
          borderTop: '1px solid var(--border-subtle)',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)'
        }}>
          <div>Page {currentPage} of {totalPages}</div>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              className="btn-icon"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(p => Math.max(p - 1, 1))}
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <button
              className="btn-icon"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage(p => Math.min(p + 1, totalPages))}
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
