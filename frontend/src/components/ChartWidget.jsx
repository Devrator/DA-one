import React, { useState } from 'react';
import { BarChart3, LineChart, PieChart, AreaChart, Download } from 'lucide-react';

export default function ChartWidget({ chartSpec, data, columns }) {
  const [activeType, setActiveType] = useState(chartSpec?.type || 'bar');

  if (!data || data.length === 0) return null;

  // Determine x-axis (labels) and y-axis (numeric values)
  const xKey = chartSpec?.x_axis || Object.keys(data[0])[0];
  const yKey = chartSpec?.y_axis || Object.keys(data[0]).find(k => {
    const val = data[0][k];
    return !isNaN(parseFloat(val)) && k !== xKey;
  }) || Object.keys(data[0])[1];

  const labels = data.slice(0, 15).map(row => String(row[xKey] ?? ''));
  const values = data.slice(0, 15).map(row => parseFloat(row[yKey]) || 0);

  const maxVal = Math.max(...values, 1);
  const minVal = Math.min(...values, 0);

  // Vibrant palette
  const colors = [
    '#6366f1', '#8b5cf6', '#ec4899', '#06b6d4', '#10b981',
    '#f59e0b', '#3b82f6', '#14b8a6', '#f43f5e', '#a855f7'
  ];

  return (
    <div className="chart-card">
      <div className="chart-header">
        <div className="chart-title">
          {chartSpec?.title || `${yKey.replace(/_/g, ' ')} by ${xKey.replace(/_/g, ' ')}`}
        </div>
        <div className="chart-type-selector">
          <button
            className={`chart-type-btn ${activeType === 'bar' ? 'active' : ''}`}
            onClick={() => setActiveType('bar')}
            title="Bar Chart"
          >
            <BarChart3 size={15} />
          </button>
          <button
            className={`chart-type-btn ${activeType === 'line' ? 'active' : ''}`}
            onClick={() => setActiveType('line')}
            title="Line Chart"
          >
            <LineChart size={15} />
          </button>
          <button
            className={`chart-type-btn ${activeType === 'pie' ? 'active' : ''}`}
            onClick={() => setActiveType('pie')}
            title="Pie / Donut Chart"
          >
            <PieChart size={15} />
          </button>
        </div>
      </div>

      <div style={{ height: '240px', width: '100%', position: 'relative', display: 'flex', alignItems: 'flex-end', padding: '1.5rem 1rem 2.5rem' }}>
        {activeType === 'bar' && (
          <div style={{ display: 'flex', width: '100%', height: '100%', alignItems: 'flex-end', gap: '12px' }}>
            {data.slice(0, 12).map((row, idx) => {
              const val = parseFloat(row[yKey]) || 0;
              const heightPct = Math.max((val / maxVal) * 100, 4);
              const label = String(row[xKey] ?? '');
              return (
                <div
                  key={idx}
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    height: '100%',
                    justifyContent: 'flex-end',
                    position: 'relative'
                  }}
                >
                  {/* Tooltip value */}
                  <div style={{
                    fontSize: '0.7rem',
                    color: '#cbd5e1',
                    marginBottom: '6px',
                    fontFamily: 'var(--font-mono)',
                    whiteSpace: 'nowrap'
                  }}>
                    {val >= 1000 ? (val >= 1000000 ? `${(val/1000000).toFixed(1)}M` : `${(val/1000).toFixed(1)}k`) : val.toLocaleString()}
                  </div>
                  {/* Animated Bar */}
                  <div
                    style={{
                      width: '100%',
                      maxWidth: '48px',
                      height: `${heightPct}%`,
                      background: `linear-gradient(180deg, ${colors[idx % colors.length]} 0%, rgba(99, 102, 241, 0.4) 100%)`,
                      borderRadius: '6px 6px 2px 2px',
                      transition: 'height 0.4s ease, transform 0.2s ease',
                      boxShadow: `0 0 12px ${colors[idx % colors.length]}44`,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.transform = 'scaleY(1.03)'}
                    onMouseLeave={(e) => e.currentTarget.style.transform = 'scaleY(1)'}
                  />
                  {/* X Axis Label */}
                  <div style={{
                    position: 'absolute',
                    bottom: '-24px',
                    fontSize: '0.72rem',
                    color: 'var(--text-secondary)',
                    maxWidth: '65px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    textAlign: 'center'
                  }}>
                    {label}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {activeType === 'line' && (
          <svg style={{ width: '100%', height: '100%', overflow: 'visible' }}>
            <defs>
              <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#6366f1" stopOpacity="0.0" />
              </linearGradient>
            </defs>
            {/* Draw Area */}
            {(() => {
              const pts = data.slice(0, 12).map((row, idx, arr) => {
                const x = (idx / (arr.length - 1 || 1)) * 100;
                const val = parseFloat(row[yKey]) || 0;
                const y = 100 - ((val / maxVal) * 85 + 5);
                return `${x}%,${y}%`;
              });
              const polyPoints = `0%,100% ${pts.join(' ')} 100%,100%`;
              return (
                <>
                  <polygon points={polyPoints} fill="url(#lineGrad)" />
                  <polyline
                    points={pts.join(' ')}
                    fill="none"
                    stroke="#818cf8"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  {pts.map((pt, i) => {
                    const [px, py] = pt.split(',');
                    return (
                      <circle
                        key={i}
                        cx={px}
                        cy={py}
                        r="5"
                        fill="#6366f1"
                        stroke="#ffffff"
                        strokeWidth="2"
                        style={{ filter: 'drop-shadow(0 0 6px #6366f1)' }}
                      />
                    );
                  })}
                </>
              );
            })()}
          </svg>
        )}

        {activeType === 'pie' && (
          <div style={{ display: 'flex', width: '100%', height: '100%', alignItems: 'center', justifyContent: 'center', gap: '2rem' }}>
            <svg viewBox="-100 -100 200 200" style={{ width: '180px', height: '180px', transform: 'rotate(-90deg)' }}>
              {(() => {
                const total = values.reduce((a, b) => a + b, 0) || 1;
                let cumulativeAngle = 0;
                return data.slice(0, 6).map((row, i) => {
                  const val = parseFloat(row[yKey]) || 0;
                  const angle = (val / total) * 360;
                  const startRad = (cumulativeAngle * Math.PI) / 180;
                  const endRad = ((cumulativeAngle + angle) * Math.PI) / 180;
                  cumulativeAngle += angle;

                  const x1 = Math.cos(startRad) * 85;
                  const y1 = Math.sin(startRad) * 85;
                  const x2 = Math.cos(endRad) * 85;
                  const y2 = Math.sin(endRad) * 85;
                  const largeArc = angle > 180 ? 1 : 0;

                  return (
                    <path
                      key={i}
                      d={`M 0 0 L ${x1} ${y1} A 85 85 0 ${largeArc} 1 ${x2} ${y2} Z`}
                      fill={colors[i % colors.length]}
                      stroke="#0f172a"
                      strokeWidth="2"
                      style={{ transition: 'all 0.3s' }}
                    />
                  );
                });
              })()}
              <circle cx="0" cy="0" r="45" fill="#141e33" />
            </svg>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {data.slice(0, 5).map((row, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.78rem' }}>
                  <div style={{ width: '10px', height: '10px', borderRadius: '2px', background: colors[i % colors.length] }} />
                  <span style={{ color: 'var(--text-secondary)' }}>{String(row[xKey] ?? '')}:</span>
                  <span style={{ color: '#ffffff', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                    {parseFloat(row[yKey]).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
