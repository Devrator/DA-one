import React, { useState } from 'react';
import { 
  FileText, Download, Eye, Calendar, Sparkles, Filter, 
  CheckCircle2, Clock, ShieldCheck, BarChart3, TrendingUp, 
  FileSpreadsheet, ArrowUpRight, Plus, RefreshCw, X
} from 'lucide-react';
import PageHeader from './PageHeader';

export default function ReportsView() {
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [previewReport, setPreviewReport] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [customReportName, setCustomReportName] = useState('Custom Q1 Regional Digest');
  const [customRegion, setCustomRegion] = useState('All Regions');

  const [reports, setReports] = useState([
    {
      id: 'REP-001',
      title: 'Executive Regional Sales & Margin Digest (2024)',
      category: 'financial',
      format: 'CSV + Executive PDF',
      time: 'Today, 08:30 AM',
      author: 'Autonomous Agent (DA-ONE)',
      status: 'Ready',
      summary: 'Comprehensive analysis of $3.64M gross sales across South, West, Central, North, and East regions with target variance and order velocity.',
      data: [
        { Region: 'South', Revenue: '$1,249,027.42', Target: '$1,100,000.00', Variance: '+13.5%', Margin: '28.4%' },
        { Region: 'West', Revenue: '$722,089.59', Target: '$700,000.00', Variance: '+3.2%', Margin: '26.8%' },
        { Region: 'Central', Revenue: '$674,225.17', Target: '$650,000.00', Variance: '+3.7%', Margin: '25.2%' },
        { Region: 'North', Revenue: '$611,925.26', Target: '$620,000.00', Variance: '-1.3%', Margin: '24.6%' },
        { Region: 'East', Revenue: '$485,213.48', Target: '$500,000.00', Variance: '-3.0%', Margin: '23.9%' },
      ]
    },
    {
      id: 'REP-002',
      title: 'AST Security & Zero-Trust Audit Compliance Report',
      category: 'security',
      format: 'Security JSON + Audit PDF',
      time: 'Yesterday, 18:00 PM',
      author: 'Security Evaluator Engine',
      status: 'Verified (100% Passed)',
      summary: 'Formal validation of 35 adversarial attack vectors. Confirms zero SQL injections, zero PII leaks, and strict row-level security policy enforcement.',
      data: [
        { Metric: 'Total Attacks Tested', Value: '35 Cases', Status: '100% Blocked' },
        { Metric: 'SQL Injection Vectors', Value: '8 Payloads', Status: 'Quarantined by AST' },
        { Metric: 'Row-Level Security Leaks', Value: '12 Scenarios', Status: '0 Violations' },
        { Metric: 'Customer PII Masking', Value: 'Customers Table', Status: 'Active Enforcement' },
      ]
    },
    {
      id: 'REP-003',
      title: 'Monthly Order Velocity & Top Customer Cohorts',
      category: 'operational',
      format: 'CSV Export',
      time: '2 days ago',
      author: 'DA-ONE Analytics',
      status: 'Ready',
      summary: 'Breakdown of 12,582 customer orders, repeat purchase rates, and top enterprise account contributions to annual recurring revenue.',
      data: [
        { Customer: 'Apex Logistics Inc.', Orders: '412', Volume: '$184,200', Loyalty: 'Platinum' },
        { Customer: 'Summit Retail Corp', Orders: '388', Volume: '$162,450', Loyalty: 'Platinum' },
        { Customer: 'BlueWave Distribution', Orders: '295', Volume: '$139,800', Loyalty: 'Gold' },
        { Customer: 'Pinnacle Technologies', Orders: '260', Volume: '$124,100', Loyalty: 'Gold' },
      ]
    },
    {
      id: 'REP-004',
      title: 'Product Catalog Margin & Discount Optimization',
      category: 'operational',
      format: 'CSV Export',
      time: '3 days ago',
      author: 'DA-ONE Analytics',
      status: 'Ready',
      summary: 'Evaluation of unit margins across 320 catalog products with dynamic price elasticity and promotional discount efficiency.',
      data: [
        { Category: 'Enterprise Hardware', Items: '84', AvgMargin: '34.2%', DiscountDrag: '2.1%' },
        { Category: 'Commercial Supplies', Items: '126', AvgMargin: '27.8%', DiscountDrag: '4.8%' },
        { Category: 'Industrial Electronics', Items: '110', AvgMargin: '31.5%', DiscountDrag: '3.2%' },
      ]
    }
  ]);

  const handleDownload = (report) => {
    const csvRows = [];
    if (report.data && report.data.length > 0) {
      const headers = Object.keys(report.data[0]);
      csvRows.push(headers.join(','));
      report.data.forEach(row => {
        csvRows.push(headers.map(h => `"${row[h] || ''}"`).join(','));
      });
    } else {
      csvRows.push("Report,Summary");
      csvRows.push(`"${report.title}","${report.summary}"`);
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${report.id}_${report.title.toLowerCase().replace(/[^a-z0-9]/g, '_')}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleCreateReport = () => {
    setIsGenerating(true);
    setTimeout(() => {
      const newRep = {
        id: `REP-00${reports.length + 1}`,
        title: customReportName,
        category: 'operational',
        format: 'Executive CSV',
        time: 'Just now',
        author: 'Executive Analyst (Deepak Sharma)',
        status: 'Generated',
        summary: `Tailored analytical digest for ${customRegion} synthesized directly from verified sales target PostgreSQL schemas.`,
        data: [
          { Parameter: 'Target Scope', Value: customRegion },
          { Parameter: 'Generated By', Value: 'Deepak Sharma' },
          { Parameter: 'Database', Value: 'querypilot_target (sales)' },
          { Parameter: 'Audit Status', Value: 'AST Verified Safe' }
        ]
      };
      setReports([newRep, ...reports]);
      setIsGenerating(false);
      setShowGenerateModal(false);
    }, 800);
  };

  const filteredReports = reports.filter(r => 
    selectedCategory === 'all' || r.category === selectedCategory
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%', maxWidth: '1320px', margin: '0 auto' }}>
      {/* Executive Page Header */}
      <PageHeader
        icon={FileText}
        title="Executive Reports & Business Intelligence"
        subtitle="Automated intelligence digests, scheduled compliance certificates, regional revenue audits, and formatted data exports."
        badge="Enterprise BI Hub"
        badgeType="copper"
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              className="btn-primary"
              onClick={() => setShowGenerateModal(true)}
            >
              <Plus size={15} />
              <span>Generate New Report</span>
            </button>
          </div>
        }
      />

      {/* 4 Report Overview KPI Cards */}
      <div className="da-kpi-grid">
        <div className="da-kpi-card da-kpi-sales">
          <div className="da-kpi-header">
            <div className="da-kpi-icon-box">
              <FileSpreadsheet size={18} />
            </div>
            <div className="da-kpi-trend-pill">
              <CheckCircle2 size={11} />
              <span>Verified</span>
            </div>
          </div>
          <div className="da-kpi-body">
            <div className="da-kpi-label">Active Briefings</div>
            <div className="da-kpi-value">{reports.length} Reports</div>
            <div className="da-kpi-subtext">All grounded in target DB</div>
          </div>
        </div>

        <div className="da-kpi-card da-kpi-orders">
          <div className="da-kpi-header">
            <div className="da-kpi-icon-box">
              <Clock size={18} />
            </div>
            <div className="da-kpi-trend-pill">
              <TrendingUp size={11} />
              <span>Automated</span>
            </div>
          </div>
          <div className="da-kpi-body">
            <div className="da-kpi-label">Scheduled Runs</div>
            <div className="da-kpi-value">Daily 08:00</div>
            <div className="da-kpi-subtext">Automated morning digests</div>
          </div>
        </div>

        <div className="da-kpi-card da-kpi-customers">
          <div className="da-kpi-header">
            <div className="da-kpi-icon-box">
              <ShieldCheck size={18} />
            </div>
            <div className="da-kpi-trend-pill">
              <CheckCircle2 size={11} />
              <span>100% Safe</span>
            </div>
          </div>
          <div className="da-kpi-body">
            <div className="da-kpi-label">AST Audit Score</div>
            <div className="da-kpi-value">100% Passed</div>
            <div className="da-kpi-subtext">Zero leakage compliance</div>
          </div>
        </div>

        <div className="da-kpi-card da-kpi-products">
          <div className="da-kpi-header">
            <div className="da-kpi-icon-box">
              <BarChart3 size={18} />
            </div>
            <div className="da-kpi-trend-pill">
              <Sparkles size={11} />
              <span>Grounded</span>
            </div>
          </div>
          <div className="da-kpi-body">
            <div className="da-kpi-label">Total Revenue Scoped</div>
            <div className="da-kpi-value">$3.64M</div>
            <div className="da-kpi-subtext">5 sales target regions</div>
          </div>
        </div>
      </div>

      {/* Filter Chips Bar */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span className="sample-label">Report Category:</span>
        {[
          { id: 'all', label: 'All Reports' },
          { id: 'financial', label: 'Financial Analytics' },
          { id: 'security', label: 'Security & Compliance' },
          { id: 'operational', label: 'Operational Performance' },
        ].map(cat => (
          <button
            key={cat.id}
            className={`prompt-chip ${selectedCategory === cat.id ? 'active' : ''}`}
            onClick={() => setSelectedCategory(cat.id)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Reports Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '1.25rem' }}>
        {filteredReports.map((r) => (
          <div key={r.id} className="da-card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span className="da-pill da-pill-session">{r.id}</span>
                <span className="da-pill da-pill-turns">{r.status}</span>
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-headings)', marginBottom: '6px' }}>
                {r.title}
              </h3>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '14px' }}>
                {r.summary}
              </p>
            </div>

            <div style={{ paddingTop: '12px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                <span>{r.time}</span> • <span>{r.format}</span>
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  className="btn-icon"
                  onClick={() => setPreviewReport(r)}
                  title="Preview report tables"
                >
                  <Eye size={13} />
                  <span>Preview</span>
                </button>
                <button
                  className="btn-icon"
                  onClick={() => handleDownload(r)}
                  style={{ color: 'var(--teal-primary)' }}
                  title="Download CSV export"
                >
                  <Download size={13} />
                  <span>Export</span>
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Report Preview Modal */}
      {previewReport && (
        <div className="modal-overlay" onClick={() => setPreviewReport(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '850px' }}>
            <div className="modal-header">
              <div>
                <span className="da-pill da-pill-session" style={{ marginBottom: '4px', display: 'inline-block' }}>{previewReport.id}</span>
                <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-headings)' }}>
                  {previewReport.title}
                </h3>
              </div>
              <button 
                onClick={() => setPreviewReport(null)}
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '1.3rem', color: 'var(--text-muted)' }}
              >
                &times;
              </button>
            </div>

            <div className="modal-body">
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
                {previewReport.summary}
              </p>

              {previewReport.data && previewReport.data.length > 0 && (
                <div className="table-wrapper" style={{ borderRadius: '10px', border: '1px solid var(--border-card)' }}>
                  <table className="styled-table">
                    <thead>
                      <tr>
                        {Object.keys(previewReport.data[0]).map((h, i) => (
                          <th key={i}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewReport.data.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {Object.values(row).map((val, cIdx) => (
                            <td key={cIdx} style={{ fontWeight: cIdx === 0 ? 600 : 400 }}>
                              {val}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn-secondary" onClick={() => setPreviewReport(null)}>
                  Close
                </button>
                <button className="btn-primary" onClick={() => handleDownload(previewReport)}>
                  <Download size={14} />
                  <span>Download Full CSV</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Generate Custom Report Modal */}
      {showGenerateModal && (
        <div className="modal-overlay" onClick={() => setShowGenerateModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '540px' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-headings)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={18} style={{ color: 'var(--copper-primary)' }} />
                <span>Configure Automated Intelligence Report</span>
              </h3>
              <button 
                onClick={() => setShowGenerateModal(false)}
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '1.3rem', color: 'var(--text-muted)' }}
              >
                &times;
              </button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label className="da-login-label" style={{ marginBottom: '5px', display: 'block' }}>Report Title</label>
                <input
                  type="text"
                  className="da-login-input"
                  value={customReportName}
                  onChange={(e) => setCustomReportName(e.target.value)}
                />
              </div>

              <div>
                <label className="da-login-label" style={{ marginBottom: '5px', display: 'block' }}>Target Region / Scope</label>
                <select
                  className="da-schema-select"
                  style={{ width: '100%', padding: '8px 12px', fontSize: '0.85rem' }}
                  value={customRegion}
                  onChange={(e) => setCustomRegion(e.target.value)}
                >
                  <option value="All Regions">All 5 Sales Regions ($3.64M Scope)</option>
                  <option value="South Region">South Region ($1.25M Leader)</option>
                  <option value="West Region">West Region ($722K)</option>
                  <option value="Central Region">Central Region ($674K)</option>
                  <option value="North Region">North Region ($612K)</option>
                  <option value="East Region">East Region ($485K)</option>
                </select>
              </div>

              <div>
                <label className="da-login-label" style={{ marginBottom: '5px', display: 'block' }}>Data Aggregation Level</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {['Daily', 'Weekly', 'Monthly Digest', 'Executive Summary'].map((freq, idx) => (
                    <span key={idx} className="da-example-chip" style={{ cursor: 'pointer' }}>
                      {freq}
                    </span>
                  ))}
                </div>
              </div>

              <div style={{ marginTop: '10px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn-secondary" onClick={() => setShowGenerateModal(false)}>
                  Cancel
                </button>
                <button className="btn-primary" onClick={handleCreateReport} disabled={isGenerating}>
                  {isGenerating ? <Activity size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  <span>{isGenerating ? 'Synthesizing...' : 'Generate Report'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
