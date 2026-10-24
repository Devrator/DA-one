import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, Database, Play, BarChart3, ShieldCheck, Clock, CheckCircle2, 
  Terminal, Layers, History, Activity, AlertCircle, ChevronRight, FileSpreadsheet, 
  RefreshCw, Cpu, Server, Compass, Shield, MessageSquare, RefreshCw as LoopIcon
} from 'lucide-react';
import ChartWidget from './components/ChartWidget';
import DataTable from './components/DataTable';
import SqlViewer from './components/SqlViewer';
import SchemaBrowser from './components/SchemaBrowser';
import BenchmarkRunner from './components/BenchmarkRunner';
import AuditLog from './components/AuditLog';
import RoleSelector from './components/RoleSelector';
import ConversationPanel from './components/ConversationPanel';
import SecurityEvaluationView from './components/SecurityEvaluationView';
import ConversationsEvaluationView from './components/ConversationsEvaluationView';
import SchemaRecoveryView from './components/SchemaRecoveryView';

const SAMPLE_PROMPTS = [
  "Show total sales by region",
  "Who are the top 5 customers by number of orders?",
  "Which products have the highest total revenue?",
  "Compare regional sales targets vs actual sales volume",
  "What is the average order value by region?",
  "Show monthly order volume trend for 2024"
];

export default function App() {
  const [activeTab, setActiveTab] = useState('workspace');
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState('');
  const [queryResult, setQueryResult] = useState(null);
  const [error, setError] = useState(null);
  const [schemaTables, setSchemaTables] = useState([]);
  const [systemReadiness, setSystemReadiness] = useState(null);
  const [queryHistory, setQueryHistory] = useState([]);
  const [schemaSearch, setSchemaSearch] = useState('');
  
  // Phase 2 State: Server-Verified Roles & Multi-Turn Sessions
  const [currentRole, setCurrentRole] = useState('executive');
  const [currentSessionId, setCurrentSessionId] = useState(`sess_${Date.now().toString(36)}`);
  const [conversationTurns, setConversationTurns] = useState([]);
  const [activeContext, setActiveContext] = useState({ metric: 'Revenue', grouping: 'All Regions' });

  const textareaRef = useRef(null);


  // Load readiness & schema on mount
  useEffect(() => {
    checkReadiness();
    fetchSchema();
    fetchRecentQueries();
  }, []);

  const checkReadiness = async () => {
    try {
      const res = await fetch('/api/v1/readiness');
      if (res.ok) {
        const data = await res.json();
        setSystemReadiness(data);
      }
    } catch (e) {
      console.warn('Backend not ready yet', e);
    }
  };

  const fetchSchema = async () => {
    try {
      const res = await fetch('/api/v1/connections/default/schema');
      if (res.ok) {
        const data = await res.json();
        setSchemaTables(data.tables || []);
      }
    } catch (e) {
      console.warn('Could not load schema', e);
    }
  };

  const fetchRecentQueries = async () => {
    try {
      const res = await fetch('/api/v1/query-history?page_size=10');
      if (res.ok) {
        const data = await res.json();
        setQueryHistory(data.items || []);
      }
    } catch (e) {
      console.warn('Could not load query history', e);
    }
  };

  const handleRunQuery = async (customPrompt) => {
    const q = (customPrompt || question).trim();
    if (!q || loading) return;

    if (customPrompt) setQuestion(customPrompt);
    setLoading(true);
    setError(null);
    setCurrentStep('Synthesizing Intent & Generating SQL...');

    const stepTimer = setTimeout(() => {
      setCurrentStep('Validating SQL AST & Security Policy...');
    }, 4000);

    const execTimer = setTimeout(() => {
      setCurrentStep('Executing Read-Only Query against PostgreSQL...');
    }, 8000);

    const explainTimer = setTimeout(() => {
      setCurrentStep('Grounding Insights & Formatting Data...');
    }, 12000);

    try {
      const res = await fetch('/api/v1/queries', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-User-Role': currentRole,
        },
        body: JSON.stringify({
          question: q,
          connection_id: 'default',
          user_role: currentRole,
          session_id: currentSessionId,
        })
      });

      clearTimeout(stepTimer);
      clearTimeout(execTimer);
      clearTimeout(explainTimer);

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server responded with ${res.status}`);
      }

      const data = await res.json();
      setQueryResult(data);
      
      // Update multi-turn session timeline
      setConversationTurns(prev => [
        ...prev,
        {
          id: data.query_id || `turn_${Date.now()}`,
          question: q,
          sql: data.generated_sql,
          status: data.status,
          result_row_count: data.result_row_count,
          execution_time_ms: data.execution_time_ms,
          clarification_message: data.status === 'clarification_needed' ? (data.clarification_question || data.error) : null,
        }
      ]);

      // Detect metric or grouping tags
      if (q.toLowerCase().includes('2023')) setActiveContext(p => ({ ...p, filter: '2023' }));
      else if (q.toLowerCase().includes('2022')) setActiveContext(p => ({ ...p, filter: '2022' }));
      if (q.toLowerCase().includes('region')) setActiveContext(p => ({ ...p, grouping: 'By Region' }));
      else if (q.toLowerCase().includes('category')) setActiveContext(p => ({ ...p, grouping: 'By Category' }));
      else if (q.toLowerCase().includes('customer')) setActiveContext(p => ({ ...p, grouping: 'By Customer' }));

      fetchRecentQueries();
    } catch (err) {
      console.error('Query execution error:', err);
      setError(err.message || 'Failed to execute query');
    } finally {
      setLoading(false);
      setCurrentStep('');
    }
  };

  const handleNewSession = () => {
    setCurrentSessionId(`sess_${Date.now().toString(36)}`);
    setConversationTurns([]);
    setQueryResult(null);
    setQuestion('');
    setActiveContext({ metric: 'Revenue', grouping: 'All Regions' });
  };


  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleRunQuery();
    }
  };

  const filteredTables = schemaTables.filter(t => 
    t.table_name.toLowerCase().includes(schemaSearch.toLowerCase())
  );

  return (
    <div className="app-container">
      {/* Top Navigation Header */}
      <header className="top-header">
        <div className="brand-section">
          <div className="brand-logo">
            <Sparkles size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="brand-title">QueryPilot AI</span>
              <span className="brand-badge">AI-02 Agent</span>
            </div>
          </div>
        </div>

        {/* View Switcher Tabs */}
        <nav className="nav-tabs">
          <button
            className={`nav-tab-btn ${activeTab === 'workspace' ? 'active' : ''}`}
            onClick={() => setActiveTab('workspace')}
          >
            <Compass size={15} />
            Analytics Workspace
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'schema' ? 'active' : ''}`}
            onClick={() => setActiveTab('schema')}
          >
            <Database size={15} />
            Schema Catalog
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'benchmark' ? 'active' : ''}`}
            onClick={() => setActiveTab('benchmark')}
          >
            <Activity size={15} />
            Benchmark (31 Cases)
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'security' ? 'active' : ''}`}
            onClick={() => setActiveTab('security')}
          >
            <Shield size={15} />
            35 Security Attacks
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'conversations' ? 'active' : ''}`}
            onClick={() => setActiveTab('conversations')}
          >
            <MessageSquare size={15} />
            50 Conversations
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'schema_recovery' ? 'active' : ''}`}
            onClick={() => setActiveTab('schema_recovery')}
          >
            <RefreshCw size={15} />
            Schema Recovery
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => setActiveTab('audit')}
          >
            <ShieldCheck size={15} />
            Audit Log
          </button>
        </nav>

        {/* System Readiness Chips & Role Switcher */}
        <div className="header-status">
          <RoleSelector currentRole={currentRole} onRoleChange={setCurrentRole} />
          <div className="status-chip" title="PostgreSQL 16 connection status">
            <div className={`pulse-dot ${systemReadiness?.database?.status === 'healthy' ? '' : 'warning'}`} />
            <span>PostgreSQL: 5433</span>
          </div>
          <div className="status-chip" title="Active open-weight LLM">
            <Cpu size={13} style={{ color: 'var(--accent-primary)' }} />
            <span>qwen2.5-coder:7b</span>
          </div>
        </div>
      </header>


      {/* Main Layout Area */}
      <div className="main-layout">
        {/* Workspace Tab Content */}
        {activeTab === 'workspace' && (
          <>
            {/* Left Schema Sidebar */}
            <aside className="schema-sidebar">
              <div className="sidebar-header">
                <span className="sidebar-title">
                  <Database size={14} /> Sales Schema
                </span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {schemaTables.length} tables
                </span>
              </div>

              <input
                type="text"
                placeholder="Filter tables..."
                className="schema-search-input"
                value={schemaSearch}
                onChange={(e) => setSchemaSearch(e.target.value)}
              />

              <div className="tables-list">
                {filteredTables.map((tbl, i) => (
                  <div key={i} className="table-item">
                    <button
                      className="table-header-btn"
                      onClick={() => handleRunQuery(`Show top 10 records from sales.${tbl.table_name}`)}
                      title={`Click to query sales.${tbl.table_name}`}
                    >
                      <div className="table-name">
                        <Layers size={13} style={{ color: '#818cf8' }} />
                        <span>{tbl.table_name}</span>
                      </div>
                      <span className="table-rows-badge">
                        {tbl.row_count != null ? tbl.row_count : '—'}
                      </span>
                    </button>
                  </div>
                ))}
              </div>

              {/* Recent Queries Mini Section */}
              {queryHistory.length > 0 && (
                <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-subtle)', padding: '0.75rem 1rem' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    <History size={12} /> Recent Queries
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                    {queryHistory.slice(0, 3).map((item, idx) => (
                      <div
                        key={idx}
                        onClick={() => handleRunQuery(item.question || item.natural_language_query)}
                        style={{
                          fontSize: '0.75rem',
                          color: 'var(--text-secondary)',
                          cursor: 'pointer',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          padding: '3px 6px',
                          borderRadius: '4px',
                          background: 'rgba(255,255,255,0.02)'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.color = 'white'}
                        onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}
                      >
                        {item.question || item.natural_language_query}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </aside>

            {/* Center Content Workspace */}
            <main className="workspace-content">
              {/* Multi-Turn Conversation History & Context Carryover */}
              <ConversationPanel
                currentSessionId={currentSessionId}
                turns={conversationTurns}
                onNewSession={handleNewSession}
                userRole={currentRole}
                activeContext={activeContext}
              />

              {/* Natural Language Prompt Card */}
              <div className="prompt-card">

                <textarea
                  ref={textareaRef}
                  className="prompt-textarea"
                  placeholder="Ask any business question in plain English (e.g. 'Show total sales by region with percentage share')..."
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={loading}
                  rows={2}
                />

                <div className="prompt-actions">
                  <div className="prompt-hints">
                    <span>Press</span>
                    <span className="kbd-shortcut">Ctrl + Enter</span>
                    <span>to execute</span>
                  </div>

                  <button
                    className="btn-primary"
                    onClick={() => handleRunQuery()}
                    disabled={loading || !question.trim()}
                  >
                    {loading ? (
                      <>
                        <Activity size={16} className="animate-spin" />
                        Analyzing...
                      </>
                    ) : (
                      <>
                        <Play size={15} fill="currentColor" />
                        Run Analysis
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Sample Prompts Chips */}
              <div className="sample-prompts-bar">
                <span className="sample-label">Examples:</span>
                {SAMPLE_PROMPTS.map((p, i) => (
                  <button
                    key={i}
                    className="prompt-chip"
                    onClick={() => handleRunQuery(p)}
                    disabled={loading}
                  >
                    {p}
                  </button>
                ))}
              </div>

              {/* Execution Loading Pipeline */}
              {loading && (
                <div className="pipeline-progress">
                  <div className="pipeline-step active">
                    <div className="step-indicator">
                      <Activity size={13} className="animate-spin" />
                    </div>
                    <span>{currentStep || 'Processing natural language query...'}</span>
                  </div>
                </div>
              )}

              {/* Error Alert */}
              {error && (
                <div style={{
                  background: 'var(--danger-bg)',
                  border: '1px solid var(--danger-border)',
                  borderRadius: 'var(--radius-md)',
                  padding: '1rem 1.25rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  color: '#fca5a5',
                  fontSize: '0.88rem'
                }}>
                  <AlertCircle size={18} style={{ color: 'var(--danger)', flexShrink: 0 }} />
                  <div>
                    <strong>Query Execution Error:</strong> {error}
                  </div>
                </div>
              )}

              {/* Query Results View */}
              {queryResult && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  {/* Grounded Business Explanation */}
                  {queryResult.explanation && (
                    <div className="explanation-card">
                      <div className="explanation-icon">
                        <Sparkles size={18} />
                      </div>
                      <div className="explanation-body">
                        <div className="explanation-title">
                          <span>Executive Summary</span>
                          <span className="grounded-badge">Grounded In Query Results</span>
                        </div>
                        <p className="explanation-text">{queryResult.explanation}</p>
                      </div>
                    </div>
                  )}

                  {/* Dynamic Interactive Chart */}
                  {queryResult.result_data && queryResult.result_data.length > 0 && (
                    <ChartWidget
                      chartSpec={queryResult.chart_spec}
                      data={queryResult.result_data}
                      columns={queryResult.result_columns}
                    />
                  )}

                  {/* Generated SQL Code Block */}
                  {queryResult.generated_sql && (
                    <SqlViewer
                      sql={queryResult.generated_sql}
                      safetyInfo={queryResult.safety_validation}
                    />
                  )}

                  {/* Interactive Data Table */}
                  {queryResult.result_data && queryResult.result_data.length > 0 && (
                    <DataTable
                      data={queryResult.result_data}
                      columns={queryResult.result_columns}
                      totalRows={queryResult.result_row_count}
                    />
                  )}

                  {/* Execution Metrics Strip */}
                  <div className="metrics-strip">
                    <div className="metric-item">
                      <Clock size={14} />
                      <span>Total Time:</span>
                      <span className="metric-val">
                        {queryResult.total_time_ms ? `${(queryResult.total_time_ms / 1000).toFixed(2)}s` : '—'}
                      </span>
                    </div>

                    <div className="metric-item">
                      <Terminal size={14} />
                      <span>DB Execution:</span>
                      <span className="metric-val">
                        {queryResult.execution_time_ms ? `${queryResult.execution_time_ms.toFixed(1)}ms` : '—'}
                      </span>
                    </div>

                    <div className="metric-item">
                      <FileSpreadsheet size={14} />
                      <span>Rows Returned:</span>
                      <span className="metric-val">{queryResult.result_row_count ?? 0}</span>
                    </div>

                    <div className="metric-item">
                      <Cpu size={14} />
                      <span>Model:</span>
                      <span className="metric-val">{queryResult.model_name || 'qwen2.5-coder:7b'}</span>
                    </div>

                    <div className="metric-item" style={{ marginLeft: 'auto' }}>
                      <ShieldCheck size={14} style={{ color: 'var(--success)' }} />
                      <span style={{ color: 'var(--success)', fontWeight: 600 }}>Read-Only Mode Enforced</span>
                    </div>
                  </div>
                </div>
              )}
            </main>
          </>
        )}

        {/* Schema Catalog Tab */}
        {activeTab === 'schema' && (
          <main className="workspace-content">
            <SchemaBrowser onSelectTableQuery={(q) => { setActiveTab('workspace'); handleRunQuery(q); }} />
          </main>
        )}

        {/* Benchmark Runner Tab */}
        {activeTab === 'benchmark' && (
          <main className="workspace-content">
            <BenchmarkRunner />
          </main>
        )}

        {/* 35-Case Adversarial Security Suite */}
        {activeTab === 'security' && (
          <main className="workspace-content">
            <SecurityEvaluationView />
          </main>
        )}

        {/* 50-Scenario Multi-Turn Conversations */}
        {activeTab === 'conversations' && (
          <main className="workspace-content">
            <ConversationsEvaluationView />
          </main>
        )}

        {/* Dynamic Schema Drift Recovery */}
        {activeTab === 'schema_recovery' && (
          <main className="workspace-content">
            <SchemaRecoveryView />
          </main>
        )}

        {/* Audit Log Tab */}
        {activeTab === 'audit' && (
          <main className="workspace-content">
            <AuditLog />
          </main>
        )}

      </div>
    </div>
  );
}
