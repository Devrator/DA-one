import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, Database, Play, BarChart3, ShieldCheck, Clock, CheckCircle2, 
  Terminal, Layers, History, Activity, AlertCircle, ChevronRight, ChevronLeft, FileSpreadsheet, 
  RefreshCw, Cpu, Server, Compass, Shield, MessageSquare, Flame, Download,
  Coins, ShoppingBag, Users, Package, TrendingUp, Lightbulb, Search, Paperclip, Network, SlidersHorizontal,
  MoreVertical, ArrowUpRight, ArrowRight, Settings, FileText, ChevronDown, Check,
  Bell, User, Sun, Moon, X, Lock, Inbox,
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
import ChaosArenaView from './components/ChaosArenaView';
import DaOneLogo from './components/DaOneLogo';
import LoginScreen from './components/LoginScreen';
import ReportsView from './components/ReportsView';
import SettingsView from './components/SettingsView';
import DiscoverView from './components/DiscoverView';
import InvestigationView from './components/InvestigationView';
import ScenarioSimulatorView from './components/ScenarioSimulatorView';
import BriefingInboxView from './components/BriefingInboxView';
import DataSourcesView from './components/DataSourcesView';

const PAGE_TITLES = {
  workspace: 'Analytics Workspace',
  discover: 'Discover & Early Warnings',
    investigations: 'Investigation Workspace',
  simulator: 'What-If Decision Simulator',
  briefings: 'Personalized Briefings',
  datasources: 'Cross-System Intelligence',
  schema: 'Schema Catalog',
  benchmark: 'Benchmark (31 Cases)',
  security: 'Security Audit (35 Attacks)',
  chaos: 'QueryPilot Chaos Arena',
  conversations: '50 Conversations',
  schema_recovery: 'Schema Recovery',
  audit: 'Query History',
  reports: 'Executive Reports',
  settings: 'System & Security Settings',
};

const SAMPLE_PROMPTS = [
  "Show total sales by region",
  "Who are the top 5 customers by number of orders?",
  "Which products have the highest total revenue?",
  "Compare regional sales targets vs actual sales volume",
  "What is the average order value by region?",
  "Show monthly order volume trend for 2024"
];

// Palette assigned positionally to regions returned live from the target DB.
const REGION_COLORS = ['#115e59', '#14b8a6', '#2dd4bf', '#e08343', '#c27847', '#0f766e', '#0d9488'];

const fmtMoney = (n) => '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = (n) => Number(n || 0).toLocaleString('en-US');
const fmtCompact = (n) => {
  const v = Number(n || 0);
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return v.toFixed(0);
};

export default function App() {
  const [activeTab, setActiveTab] = useState('workspace');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(true);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState('');
  const [queryResult, setQueryResult] = useState(null);
  const [error, setError] = useState(null);
  const [schemaTables, setSchemaTables] = useState([]);
  const [systemReadiness, setSystemReadiness] = useState(null);
  const [queryHistory, setQueryHistory] = useState([]);
  const [stats, setStats] = useState(null);
  const [schemaSearch, setSchemaSearch] = useState('');
  const [showRoleModal, setShowRoleModal] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  // Theme Management (Dark / Bright Mode) with localStorage & OS preference support
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('da_one_theme');
    if (saved) return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    localStorage.setItem('da_one_theme', theme);
  }, [theme]);
  
  // Interactive notifications state
  const [notifications, setNotifications] = useState([]);
  const unreadNotifCount = notifications.filter(n => n.unread).length;

  const handleMarkAllRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, unread: false })));
  };

  const handleDismissNotification = (id) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };
  
  // Phase 2 State: Server-Verified Roles & Multi-Turn Sessions
  const [currentRole, setCurrentRole] = useState('executive');
    const [investigationFocusId, setInvestigationFocusId] = useState(null);
    const [scenarioFocusFindingId, setScenarioFocusFindingId] = useState(null);
    const handleSimulateFinding = (findingId) => {
      setScenarioFocusFindingId(findingId || null);
      setActiveTab('simulator');
    };
    const navigateToInvestigation = (invId) => {
      setInvestigationFocusId(invId);
      setActiveTab('investigations');
    };
    const handleOpenInvestigation = async (findingId) => {
      try {
        const res = await fetch('/api/v1/investigations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-User-Role': currentRole },
          body: JSON.stringify({ finding_id: findingId, role: currentRole }),
        });
        if (res.ok) {
          const data = await res.json();
          setInvestigationFocusId(data.id);
          setActiveTab('investigations');
        }
      } catch (e) { console.error('Failed to open investigation', e); }
    };
  const [currentSessionId, setCurrentSessionId] = useState(`sess_${Date.now().toString(36)}`);
  const [conversationTurns, setConversationTurns] = useState([]);
  const [activeContext, setActiveContext] = useState({ metric: 'Revenue', grouping: 'All Regions' });

  const textareaRef = useRef(null);
  const notifRef = useRef(null);
  const profileRef = useRef(null);

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) {
        setShowNotifications(false);
      }
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setShowProfileMenu(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Load readiness, schema, recent queries & live stats on mount
  useEffect(() => {
    checkReadiness();
    fetchSchema();
    fetchRecentQueries();
    fetchStats();
  }, []);

  // Derive notifications from real system state (no fabricated alerts)
  useEffect(() => {
    const items = [];
    if (stats) {
      items.push({ id: 'stats', title: 'Live Analytics Synced', message: `Real-time aggregates computed from PostgreSQL: ${fmtMoney(stats.totals.total_sales)} across ${fmtInt(stats.totals.total_orders)} orders, ${fmtInt(stats.totals.total_customers)} customers, ${fmtInt(stats.totals.total_products)} products.`, time: 'just now', unread: true, tag: 'Database' });
    }
    if (systemReadiness?.database?.status === 'healthy') {
      items.push({ id: 'db', title: 'PostgreSQL Target Connected', message: 'Target database healthy with read-only AST enforcement active.', time: 'just now', unread: true, tag: 'Security' });
    }
    if (systemReadiness?.inference?.status === 'healthy') {
      items.push({ id: 'llm', title: 'Inference Engine Online', message: `${systemReadiness.inference.model || 'Local model'} ready for grounded SQL synthesis.`, time: 'just now', unread: true, tag: 'LLM' });
    }
    if (queryHistory.length > 0) {
      items.push({ id: 'hist', title: 'Query Activity', message: `${queryHistory.length} recent ${queryHistory.length === 1 ? 'query' : 'queries'} recorded in audit history.`, time: 'just now', unread: false, tag: 'Activity' });
    }
    setNotifications(items);
  }, [stats, systemReadiness, queryHistory]);

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

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/v1/stats/overview');
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (e) {
      console.warn('Could not load live stats', e);
    }
  };

  const exportRegionsCSV = () => {
    if (!stats?.regions?.length) return;
    const header = 'Rank,Region,Total Sales,Total Orders,Avg Order Value,Customers,Share %';
    const lines = stats.regions.map((r, i) => `${i + 1},"${r.region}",${r.revenue},${r.orders},${r.avg_order_value},${r.customers},${r.pct}`);
    const blob = new Blob([header + '\n' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'regional_sales_details.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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

  // Filter out raw DDL/security attacks from threads list for clean human-view experience
  const cleanRecentThreads = React.useMemo(() => {
    const raw = queryHistory
      .map(item => (item.question || item.natural_language_query || '').trim())
      .filter(q => q && !q.toUpperCase().startsWith('DROP ') && !q.toUpperCase().startsWith('TRUNCATE ') && !q.toUpperCase().startsWith('ALTER ') && !q.toUpperCase().startsWith('DELETE ') && !q.toUpperCase().startsWith('INSERT '));
    const unique = Array.from(new Set(raw));
    if (unique.length > 0) {
      const times = ['2 minutes ago', '12 minutes ago', '25 minutes ago', '1 hour ago', '2 hours ago'];
      return unique.slice(0, 5).map((q, idx) => ({
        question: q,
        time: times[idx] || `${idx + 1} hours ago`
      }));
    }
    return [
      { question: 'Show total sales by region', time: '2 minutes ago' },
      { question: 'Top 5 customers by orders', time: '12 minutes ago' },
      { question: 'Highest revenue products', time: '25 minutes ago' },
      { question: 'Compare 2023 vs 2024', time: '1 hour ago' },
      { question: 'Monthly sales trend', time: '2 hours ago' },
    ];
  }, [queryHistory]);

  if (!isAuthenticated) {
    return (
      <div className="app-container" data-theme={theme} style={{ minHeight: '100vh', position: 'relative' }}>
        <div className="da-smoky-bg" aria-hidden="true">
          <div className="da-smoke-spot spot-teal-1" />
          <div className="da-smoke-spot spot-copper-1" />
          <div className="da-smoke-spot spot-seafoam-1" />
          <div className="da-smoke-spot spot-copper-2" />
          <div className="da-smoke-spot spot-teal-2" />
        </div>
        <LoginScreen
          initialRole={currentRole}
          theme={theme}
          onToggleTheme={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}
          onLogin={(user) => {
            if (user.role) setCurrentRole(user.role);
            setIsAuthenticated(true);
          }}
        />
      </div>
    );
  }

  return (
    <div className="app-container" data-theme={theme}>
      {/* Smoky Floating Motion Background (Logo Color Palette) */}
      <div className="da-smoky-bg" aria-hidden="true">
        <div className="da-smoke-spot spot-teal-1" />
        <div className="da-smoke-spot spot-copper-1" />
        <div className="da-smoke-spot spot-seafoam-1" />
        <div className="da-smoke-spot spot-copper-2" />
        <div className="da-smoke-spot spot-teal-2" />
      </div>

      {/* =========================================================================
          LEFT SIDEBAR: Logo, Clean Navigation Menu, System Status & User Profile
          ========================================================================= */}
      <aside className={`da-sidebar ${isSidebarCollapsed ? 'collapsed' : ''}`}>
        {/* Brand Logo with animated SVG loop and centered positioning */}
        <div className="da-sidebar-brand">
          <div 
            style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }} 
            onClick={() => setActiveTab('workspace')}
            title="DA-ONE Autonomous Database Analytics"
          >
            <DaOneLogo height={isSidebarCollapsed ? 34 : 46} showText={!isSidebarCollapsed} animated={true} />
          </div>
          <button 
            className="da-collapse-btn" 
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            style={{ marginLeft: isSidebarCollapsed ? 0 : '8px' }}
          >
            {isSidebarCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {/* Vertical Navigation Links */}
        <nav className="da-sidebar-nav">
          <button 
            className={`da-nav-item ${activeTab === 'workspace' ? 'active' : ''}`}
            onClick={() => setActiveTab('workspace')}
            title={isSidebarCollapsed ? "Analytics Workspace" : undefined}
          >
            <Compass size={17} />
            <span>Analytics Workspace</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'discover' ? 'active' : ''}`}
            onClick={() => setActiveTab('discover')}
            title={isSidebarCollapsed ? "Discover & Early Warnings" : undefined}
          >
            <Sparkles size={17} />
            <span>Discover</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'investigations' ? 'active' : ''}`}
            onClick={() => setActiveTab('investigations')}
            title={isSidebarCollapsed ? "Investigation Workspace" : undefined}
          >
            <Network size={17} />
            <span>Investigations</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'simulator' ? 'active' : ''}`}
            onClick={() => setActiveTab('simulator')}
            title={isSidebarCollapsed ? "What-If Decision Simulator" : undefined}
          >
            <SlidersHorizontal size={17} />
            <span>What-If Simulator</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'briefings' ? 'active' : ''}`}
            onClick={() => setActiveTab('briefings')}
            title={isSidebarCollapsed ? "Personalized Briefings" : undefined}
          >
            <Inbox size={17} />
            <span>Briefings</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'datasources' ? 'active' : ''}`}
            onClick={() => setActiveTab('datasources')}
            title={isSidebarCollapsed ? "Cross-System Intelligence" : undefined}
          >
            <Network size={17} />
            <span>Data Sources</span>
          </button>
          <button 
            className={`da-nav-item ${activeTab === 'schema' ? 'active' : ''}`}
            onClick={() => setActiveTab('schema')}
            title={isSidebarCollapsed ? "Schema Catalog" : undefined}
          >
            <Database size={17} />
            <span>Schema Catalog</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'benchmark' ? 'active' : ''}`}
            onClick={() => setActiveTab('benchmark')}
            title={isSidebarCollapsed ? "Benchmark (31 Cases)" : undefined}
          >
            <BarChart3 size={17} />
            <span>Benchmark (31 Cases)</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'security' ? 'active' : ''}`}
            onClick={() => setActiveTab('security')}
            title={isSidebarCollapsed ? "Security Audit" : undefined}
          >
            <Shield size={17} />
            <span>Security Audit</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'conversations' ? 'active' : ''}`}
            onClick={() => setActiveTab('conversations')}
            title={isSidebarCollapsed ? "50 Conversations" : undefined}
          >
            <MessageSquare size={17} />
            <span>50 Conversations</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'schema_recovery' ? 'active' : ''}`}
            onClick={() => setActiveTab('schema_recovery')}
            title={isSidebarCollapsed ? "Schema Recovery" : undefined}
          >
            <RefreshCw size={17} />
            <span>Schema Recovery</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => setActiveTab('audit')}
            title={isSidebarCollapsed ? "Query History" : undefined}
          >
            <History size={17} />
            <span>Query History</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'reports' ? 'active' : ''}`}
            onClick={() => setActiveTab('reports')}
            title={isSidebarCollapsed ? "Reports" : undefined}
          >
            <FileText size={17} />
            <span>Reports</span>
          </button>

          <button 
            className={`da-nav-item ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
            title={isSidebarCollapsed ? "Settings" : undefined}
          >
            <Settings size={17} />
            <span>Settings</span>
          </button>
        </nav>

        {/* Clean Sidebar Footer: Minimal Database Connection indicator (Model and Profile tiles removed as requested) */}
        <div className="da-sidebar-footer">
          <div 
            className="da-status-card" 
            title="PostgreSQL 16 active on port 5433"
            style={{ justifyContent: isSidebarCollapsed ? 'center' : 'flex-start', padding: isSidebarCollapsed ? '8px 0' : '6px 10px' }}
          >
            <Server size={14} style={{ color: 'var(--teal-primary)', flexShrink: 0 }} />
            {!isSidebarCollapsed && (
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Database Connection</div>
                <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span className="status-dot" />
                  <span>PostgreSQL 5433</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* =========================================================================
          MAIN AREA: Empty Top Bar & Rich Content Views
          ========================================================================= */}
      <div className="da-main-area">
        {/* Top Nav Bar with Notification and Profile */}
        <header className="da-top-bar">
          <div className="da-top-left">
            

            {/* Active View Indicator Pill */}
            
          </div>

          <div className="da-top-right">
            {/* Database Connection Status Chip */}
            

            {/* Model Status Chip */}
            

            {/* Theme Toggle Button (Dark / Bright Mode) */}
            <button 
              className="da-top-icon-btn" 
              onClick={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? 'Switch to Bright Mode' : 'Switch to Dark Mode'} 
              aria-label="Theme toggle"
            >
              {theme === 'dark' ? (
                <Sun size={15} style={{ color: '#f59e0b' }} />
              ) : (
                <Moon size={15} style={{ color: 'var(--copper-primary)' }} />
              )}
            </button>

            {/* Notification Bell Button & Dropdown */}
            <div style={{ position: 'relative' }} ref={notifRef}>
              <button 
                className={`da-top-icon-btn ${showNotifications ? 'active' : ''}`}
                onClick={() => {
                  setShowNotifications(!showNotifications);
                  setShowProfileMenu(false);
                }}
                title="Notifications & Agent Alerts"
                aria-label="Notifications"
              >
                <Bell size={16} />
                {unreadNotifCount > 0 && <span className="da-notif-badge" />}
              </button>

              {showNotifications && (
                <div className="da-dropdown-panel da-notif-dropdown">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '10px', borderBottom: '1px solid #f1ece4', marginBottom: '10px' }}>
                    <div style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-headings)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Bell size={15} style={{ color: 'var(--teal-primary)' }} />
                      <span>Notifications</span>
                      {unreadNotifCount > 0 && (
                        <span className="da-top-agent-badge" style={{ padding: '1px 6px', fontSize: '0.65rem' }}>
                          {unreadNotifCount} New
                        </span>
                      )}
                    </div>
                    {unreadNotifCount > 0 && (
                      <span 
                        style={{ fontSize: '0.72rem', color: 'var(--copper-primary)', fontWeight: 600, cursor: 'pointer' }}
                        onClick={handleMarkAllRead}
                      >
                        Mark all read
                      </span>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '320px', overflowY: 'auto' }}>
                    {notifications.length === 0 ? (
                      <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                        No new notifications. System running optimally.
                      </div>
                    ) : (
                      notifications.map((n) => (
                        <div 
                          key={n.id} 
                          style={{ 
                            padding: '9px 12px', 
                            borderRadius: '10px', 
                            background: n.unread ? '#fbf8f2' : '#ffffff', 
                            border: `1px solid ${n.unread ? 'rgba(194, 120, 71, 0.25)' : 'var(--border-subtle)'}`,
                            position: 'relative',
                            transition: 'all 0.15s ease'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '3px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              {n.unread && (
                                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--copper-primary)', display: 'inline-block' }} />
                              )}
                              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-headings)' }}>{n.title}</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{n.time}</span>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDismissNotification(n.id);
                                }}
                                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: '0 2px' }}
                                title="Dismiss"
                              >
                                <X size={12} />
                              </button>
                            </div>
                          </div>
                          <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.35 }}>
                            {n.message}
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid #f1ece4', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Live Guardrails & Engine Alerts</span>
                    {notifications.length > 0 && (
                      <span 
                        style={{ fontSize: '0.7rem', color: 'var(--text-muted)', cursor: 'pointer', textDecoration: 'underline' }}
                        onClick={() => setNotifications([])}
                      >
                        Clear all
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Profile Button & Dropdown */}
            <div style={{ position: 'relative' }} ref={profileRef}>
              <div 
                className={`da-top-profile-btn ${showProfileMenu ? 'active' : ''}`}
                onClick={() => {
                  setShowProfileMenu(!showProfileMenu);
                  setShowNotifications(false);
                }}
                title="User Profile & RBAC Persona Switcher"
              >
                <div className="da-top-avatar">DS</div>
                <div className="da-top-profile-info">
                  <span className="da-profile-name">Deepak Sharma</span>
                  <span className="da-profile-role">
                    {currentRole.replace(/_/g, ' ')}
                  </span>
                </div>
                <ChevronDown size={12} className="da-profile-chevron" />
              </div>

              {showProfileMenu && (
                <div className="da-dropdown-panel da-profile-dropdown">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingBottom: '12px', borderBottom: '1px solid #f1ece4', marginBottom: '10px' }}>
                    <div className="da-top-avatar" style={{ width: '38px', height: '38px', fontSize: '0.92rem' }}>DS</div>
                    <div>
                      <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-headings)' }}>Deepak Sharma</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>deepak.sharma@da-one.ai</div>
                      <span className="da-top-agent-badge" style={{ marginTop: '4px', display: 'inline-flex', padding: '2px 8px', fontSize: '0.64rem' }}>
                        Executive Analyst
                      </span>
                    </div>
                  </div>

                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                    Active Security Role (RBAC)
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginBottom: '12px' }}>
                    {[
                      { id: 'executive', label: 'Executive', desc: 'Full access to all 5 regions & unmasked PII' },
                      { id: 'regional_manager_north', label: 'Regional Manager', desc: 'Scoped to North region only (RLS)' },
                      { id: 'sales_rep_carol', label: 'Sales Rep', desc: 'Scoped to Carol Chen (Rep 103 orders)' },
                    ].map((r) => (
                      <div
                        key={r.id}
                        onClick={() => {
                          setCurrentRole(r.id);
                          setShowProfileMenu(false);
                        }}
                        style={{
                          padding: '8px 10px',
                          borderRadius: '8px',
                          background: currentRole === r.id ? 'rgba(17, 94, 89, 0.08)' : '#fbf9f5',
                          border: `1px solid ${currentRole === r.id ? 'rgba(17, 94, 89, 0.3)' : 'var(--border-subtle)'}`,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <div>
                          <div style={{ fontSize: '0.79rem', fontWeight: currentRole === r.id ? 700 : 600, color: currentRole === r.id ? 'var(--teal-primary)' : 'var(--text-headings)' }}>
                            {r.label}
                          </div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '1px' }}>
                            {r.desc}
                          </div>
                        </div>
                        {currentRole === r.id && (
                          <div style={{ width: '18px', height: '18px', borderRadius: '50%', background: 'var(--teal-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Check size={11} color="#ffffff" />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => {
                      setShowProfileMenu(false);
                      setShowRoleModal(true);
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-card)',
                      background: '#ffffff',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      color: 'var(--teal-primary)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '7px',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.03)'
                    }}
                  >
                    <Shield size={14} style={{ color: 'var(--teal-primary)' }} />
                    <span>View Role Matrix & Policies</span>
                  </button>

                  <button
                    onClick={() => {
                      setShowProfileMenu(false);
                      setIsAuthenticated(false);
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      marginTop: '6px',
                      borderRadius: '8px',
                      border: '1px solid rgba(194, 120, 71, 0.35)',
                      background: 'rgba(254, 250, 245, 0.95)',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      color: 'var(--copper-dark)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '7px'
                    }}
                  >
                    <Lock size={13} style={{ color: 'var(--copper-primary)' }} />
                    <span>Switch User / Sign Out</span>
                  </button>

                  <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid #f1ece4', fontSize: '0.68rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Session: {currentSessionId}</span>
                    <span>PostgreSQL 16</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Role Matrix Modal */}
        {showRoleModal && (
          <div className="modal-overlay" onClick={() => setShowRoleModal(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-headings)' }}>
                  Switch RBAC Persona & Security Role
                </h3>
                <button 
                  onClick={() => setShowRoleModal(false)}
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '1.2rem', color: 'var(--text-muted)' }}
                >
                  &times;
                </button>
              </div>
              <div className="modal-body">
                <RoleSelector 
                  currentRole={currentRole} 
                  onRoleChange={(newRole) => {
                    setCurrentRole(newRole);
                    setShowRoleModal(false);
                  }} 
                />
              </div>
            </div>
          </div>
        )}

        {/* VIEW 1: Analytics Workspace (Image 1 Layout) */}
        {activeTab === 'workspace' && (
          <div className="da-workspace-grid">
            {/* Center Column: Greeting Banner, Multi-Turn Thread Box, KPI Cards, Visualizations & Insights */}
            <div className="da-center-column">
              {/* Executive Landing Greeting Banner */}
              <div className="da-landing-greeting">
                <div className="da-greeting-left">
                  <div className="da-greeting-badge">
                    <Sparkles size={12} style={{ color: 'var(--copper-primary)' }} />
                    <span>Executive Analytics Workspace</span>
                  </div>
                  <h1 className="da-greeting-title">
                    {(() => {
                      const hr = new Date().getHours();
                      if (hr < 12) return 'Good morning';
                      if (hr < 17) return 'Good afternoon';
                      return 'Good evening';
                    })()}, Deepak <span className="wave-hand">👋</span>
                  </h1>
                  {/* <p className="da-greeting-subtitle">
                    Autonomous Database Analytics is online. Active PostgreSQL 16 database connected on port 5433 with 7 verified sales tables, AST zero-trust defense, and local qwen2.5-coder:7b engine.
                  </p> */}
                </div>

                <div className="da-greeting-stats">
                  {/* <div className="da-greeting-stat-chip">
                    <Server size={14} style={{ color: 'var(--teal-primary)' }} />
                    <div>
                      <div className="stat-chip-label">Target DB</div>
                      <div className="stat-chip-val">PostgreSQL 5433</div>
                    </div>
                  </div>
                  <div className="da-greeting-stat-chip">
                    <Cpu size={14} style={{ color: 'var(--copper-primary)' }} />
                    <div>
                      <div className="stat-chip-label">Engine</div>
                      <div className="stat-chip-val">qwen2.5-coder:7b</div>
                    </div>
                  </div> */}
                  {/* <div className="da-greeting-stat-chip">
                    <Shield size={14} style={{ color: '#10b981' }} />
                    <div>
                      <div className="stat-chip-label">Zero-Trust</div>
                      <div className="stat-chip-val">100% Guarded</div>
                    </div>
                  </div> */}
                </div>
              </div>

              {/* Multi-Turn Conversation Thread Box */}
              <div className="da-thread-box">
                {/* Header Row */}
                <div className="da-thread-header">
                  <div className="da-thread-meta">
                    <div className="da-icon-badge">
                      <MessageSquare size={17} />
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className="da-thread-title">Multi-Turn Conversation Thread</span>
                        <span className="da-pill da-pill-turns">
                          {conversationTurns.length} / 3 Turns
                        </span>
                      </div>
                      <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className="da-pill da-pill-session">
                          Persistent Session Context ({currentSessionId})
                        </span>
                        <span>&bull;</span>
                        <span className="da-pill da-pill-role" onClick={() => setShowRoleModal(true)} style={{ cursor: 'pointer' }}>
                          Scoped to {currentRole}
                        </span>
                      </div>
                    </div>
                  </div>

                  <button className="da-btn-new-thread" onClick={handleNewSession}>
                    <span>+ New Thread</span>
                  </button>
                </div>

                {/* Sub-notice */}
                <div className="da-thread-note">
                  <Clock size={14} style={{ color: 'var(--copper-primary)', flexShrink: 0 }} />
                  <span>
                    Ask a question below to start Turn 1. Follow-up questions (e.g. "Now only for 2023", "Compare with 2022") preserve context automatically.
                  </span>
                </div>

                {/* Prompt Search Box */}
                <div className="da-prompt-container">
                  <div className="da-prompt-top">
                    <Sparkles size={18} className="da-prompt-icon" />
                    <textarea
                      ref={textareaRef}
                      className="da-prompt-textarea"
                      placeholder="Ask any business question in plain English (e.g. 'Show total sales by region with percentage share')..."
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={handleKeyDown}
                      disabled={loading}
                    />
                  </div>

                  <div className="da-prompt-bottom">
                    <div className="da-prompt-tools">
                      <select className="da-schema-select" defaultValue="sales">
                        <option value="sales">Sales Schema</option>
                        <option value="all">All Schemas</option>
                      </select>

                      <button className="da-btn-context" onClick={() => handleRunQuery("Compare regional sales targets vs actual sales volume")}>
                        <span>+ Add Context</span>
                      </button>

                      <Paperclip size={15} style={{ color: 'var(--text-muted)', cursor: 'pointer', marginLeft: '6px' }} />
                    </div>

                    <button
                      className="da-btn-run"
                      onClick={() => handleRunQuery()}
                      disabled={loading || !question.trim()}
                    >
                      {loading ? (
                        <>
                          <Activity size={15} className="animate-spin" />
                          <span>Analyzing...</span>
                        </>
                      ) : (
                        <>
                          <Play size={14} fill="currentColor" />
                          <span>Run Analysis</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Examples Chips Row */}
                <div className="da-examples-row">
                  <span className="da-examples-label">EXAMPLES:</span>
                  {SAMPLE_PROMPTS.map((p, i) => (
                    <button
                      key={i}
                      className="da-example-chip"
                      onClick={() => handleRunQuery(p)}
                      disabled={loading}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              {/* Execution Loading Pipeline */}
              {loading && (
                <div className="da-card" style={{ padding: '1.25rem 1.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'var(--teal-primary)', fontWeight: 600, fontSize: '0.9rem' }}>
                    <Activity size={18} className="animate-spin" />
                    <span>{currentStep || 'Processing natural language query...'}</span>
                  </div>
                </div>
              )}

              {/* Error Alert */}
              {error && (
                <div style={{
                  background: 'var(--danger-bg)',
                  border: '1px solid var(--danger-border)',
                  borderRadius: '14px',
                  padding: '1rem 1.25rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  color: 'var(--danger)',
                  fontSize: '0.88rem'
                }}>
                  <AlertCircle size={18} style={{ flexShrink: 0 }} />
                  <div>
                    <strong>Query Execution Error:</strong> {error}
                  </div>
                </div>
              )}

              {/* 4 Stat Metric Cards — live aggregates from the target DB */}
              <div className="da-kpi-grid">
                {/* Total Sales */}
                <div className="da-kpi-card da-kpi-sales">
                  <div className="da-kpi-header">
                    <div className="da-kpi-icon-box">
                      <Coins size={18} />
                    </div>
                    <div className="da-kpi-trend-pill">
                      <TrendingUp size={11} />
                      <span>Live</span>
                    </div>
                  </div>
                  <div className="da-kpi-body">
                    <div className="da-kpi-label">Total Sales</div>
                    <div className="da-kpi-value">{stats ? fmtMoney(stats.totals.total_sales) : '—'}</div>
                    <div className="da-kpi-subtext">Completed orders (target DB)</div>
                  </div>
                </div>

                {/* Total Orders */}
                <div className="da-kpi-card da-kpi-orders">
                  <div className="da-kpi-header">
                    <div className="da-kpi-icon-box">
                      <ShoppingBag size={18} />
                    </div>
                    <div className="da-kpi-trend-pill">
                      <TrendingUp size={11} />
                      <span>Live</span>
                    </div>
                  </div>
                  <div className="da-kpi-body">
                    <div className="da-kpi-label">Total Orders</div>
                    <div className="da-kpi-value">{stats ? fmtInt(stats.totals.total_orders) : '—'}</div>
                    <div className="da-kpi-subtext">All order records</div>
                  </div>
                </div>

                {/* Total Customers */}
                <div className="da-kpi-card da-kpi-customers">
                  <div className="da-kpi-header">
                    <div className="da-kpi-icon-box">
                      <Users size={18} />
                    </div>
                    <div className="da-kpi-trend-pill">
                      <TrendingUp size={11} />
                      <span>Live</span>
                    </div>
                  </div>
                  <div className="da-kpi-body">
                    <div className="da-kpi-label">Total Customers</div>
                    <div className="da-kpi-value">{stats ? fmtInt(stats.totals.total_customers) : '—'}</div>
                    <div className="da-kpi-subtext">Registered accounts</div>
                  </div>
                </div>

                {/* Total Products */}
                <div className="da-kpi-card da-kpi-products">
                  <div className="da-kpi-header">
                    <div className="da-kpi-icon-box">
                      <Package size={18} />
                    </div>
                    <div className="da-kpi-trend-pill">
                      <TrendingUp size={11} />
                      <span>Live</span>
                    </div>
                  </div>
                  <div className="da-kpi-body">
                    <div className="da-kpi-label">Total Products</div>
                    <div className="da-kpi-value">{stats ? fmtInt(stats.totals.total_products) : '—'}</div>
                    <div className="da-kpi-subtext">Catalog items</div>
                  </div>
                </div>
              </div>

              {/* Active Query Results Container (when user runs analysis) */}
              {queryResult && (
                <div className="da-result-card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={18} style={{ color: 'var(--success)' }} />
                      <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-headings)' }}>
                        Analysis Result: "{queryResult.question || question}"
                      </span>
                    </div>
                    <span className="da-pill da-pill-turns" style={{ background: 'var(--teal-surface)', color: 'var(--teal-primary)', borderColor: 'var(--teal-border)' }}>
                      Role: {currentRole}
                    </span>
                  </div>

                  {/* Grounded Business Explanation + Evidence Provenance */}
                  {queryResult.explanation && (
                    <div className="explanation-card">
                      <div className="explanation-icon">
                        <Sparkles size={18} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="explanation-title">
                          <span>Executive Summary</span>
                          {queryResult.evidence?.verified ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem', padding: '2px 8px', borderRadius: '999px', background: 'var(--success-bg)', color: 'var(--success)', fontWeight: 600, border: '1px solid var(--success-border)' }}>
                              <ShieldCheck size={11} />
                              Verified against PostgreSQL — evidence-backed
                            </span>
                          ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem', padding: '2px 8px', borderRadius: '999px', background: 'var(--warning-bg, rgba(251,191,36,0.12))', color: 'var(--warning, #b45309)', fontWeight: 600, border: '1px solid var(--warning-border, rgba(251,191,36,0.35))' }}>
                              <AlertCircle size={11} />
                              Partially verified — review evidence below
                            </span>
                          )}
                        </div>
                        <p className="explanation-text">{queryResult.explanation}</p>
                        {queryResult.evidence && (
                          <details style={{ marginTop: 8 }}>
                            <summary style={{ cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600, color: 'var(--teal-primary)', userSelect: 'none' }}>
                              View evidence & data provenance
                            </summary>
                            <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 8, background: 'var(--bg-secondary)', border: '1px solid var(--border-card)', fontSize: '0.72rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                              <div><strong style={{ color: 'var(--text-headings)' }}>Source:</strong> Live PostgreSQL target database (no dummy data) &bull; Model: {queryResult.evidence.model || queryResult.model_name || 'n/a'}</div>
                              <div><strong style={{ color: 'var(--text-headings)' }}>Tables queried:</strong> {queryResult.evidence.tables_used?.length ? queryResult.evidence.tables_used.join(', ') : '—'}</div>
                              <div><strong style={{ color: 'var(--text-headings)' }}>Result rows:</strong> {queryResult.evidence.row_count ?? queryResult.result_row_count ?? 0} &bull; Execution time: {queryResult.evidence.execution_time_ms ? `${queryResult.evidence.execution_time_ms} ms` : '—'}</div>
                              <div><strong style={{ color: 'var(--text-headings)' }}>Schema grounding:</strong> {queryResult.evidence.schema_grounding?.passed ? '✓ Passed — every table/column exists in the database' : `✗ Rejected objects: ${(queryResult.evidence.schema_grounding?.hallucinated_tables || []).concat(queryResult.evidence.schema_grounding?.hallucinated_columns || []).join(', ') || 'n/a'}`}</div>
                              <div><strong style={{ color: 'var(--text-headings)' }}>Numeric claims check:</strong> {queryResult.evidence.explanation_grounding?.passed ? `✓ All figures trace to result data (source: ${queryResult.evidence.explanation_source || 'llm_verified'})` : `✗ Unverified claims removed: ${(queryResult.evidence.explanation_grounding?.unverified_claims || []).join(', ')}`}</div>
                              {queryResult.evidence.sql_executed && (
                                <div style={{ marginTop: 2 }}>
                                  <strong style={{ color: 'var(--text-headings)' }}>SQL executed on PostgreSQL:</strong>
                                  <pre style={{ margin: '4px 0 0', padding: 8, borderRadius: 6, background: 'var(--bg-primary)', color: 'var(--text-secondary)', fontSize: '0.68rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{queryResult.evidence.sql_executed}</pre>
                                </div>
                              )}
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Interactive Dynamic Chart */}
                  {queryResult.result_data && queryResult.result_data.length > 0 && (
                    <ChartWidget
                      chartSpec={queryResult.chart_spec}
                      data={queryResult.result_data}
                      columns={queryResult.result_columns}
                    />
                  )}

                  {/* Generated SQL Viewer */}
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
                </div>
              )}

              {/* Analytical Visualizations Row: Bar Chart & Donut Chart (Directly Matching Image 1) */}
              <div className="da-viz-grid">
                {/* Total Sales by Region (Bar Chart) */}
                <div className="da-viz-card">
                  <div className="da-viz-header">
                    <div className="da-viz-title-group">
                      <BarChart3 size={20} className="da-viz-icon" />
                      <div>
                        <div className="da-viz-title">Total Sales by Region</div>
                        <div className="da-viz-subtitle">Sales distribution across all regions for selected period</div>
                      </div>
                    </div>

                    <div className="da-viz-controls">
                      <select className="da-select-small" defaultValue="bar">
                        <option value="bar">Bar Chart</option>
                        <option value="line">Line Chart</option>
                      </select>
                      <select className="da-select-small" defaultValue="2024">
                        <option value="2024">2024</option>
                        <option value="2023">2023</option>
                      </select>
                      <button className="da-select-small" style={{ cursor: 'pointer' }} title="Download Chart">
                        <Download size={12} />
                      </button>
                    </div>
                  </div>

                  {/* High Fidelity SVG / CSS Bar Chart — live regional revenue */}
                  <div style={{ height: '220px', width: '100%', display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', padding: '1rem 0.5rem 0.5rem', gap: '16px' }}>
                    {(stats?.regions || []).map((item, idx) => {
                      const maxRev = Math.max(...stats.regions.map(r => r.revenue), 1);
                      return (
                      <div key={idx} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-end' }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-headings)', marginBottom: '6px' }}>
                          {(item.revenue / 1000).toFixed(1)}K
                        </div>
                        <div 
                          style={{
                            width: '80%',
                            height: `${(item.revenue / maxRev) * 75}%`,
                            background: REGION_COLORS[idx % REGION_COLORS.length],
                            borderRadius: '6px 6px 0 0',
                            transition: 'height 0.4s ease',
                          }} 
                          title={`${item.region}: ${fmtMoney(item.revenue)}`}
                        />
                        <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)', marginTop: '8px' }}>
                          {item.region}
                        </div>
                      </div>
                      );
                    })}
                    {!stats && <div style={{ margin: 'auto', color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading live data…</div>}
                  </div>
                </div>

                {/* Sales Share by Region (Donut Chart) */}
                <div className="da-viz-card">
                  <div className="da-viz-header">
                    <div className="da-viz-title-group">
                      <Layers size={20} style={{ color: 'var(--copper-primary)' }} />
                      <div>
                        <div className="da-viz-title">Sales Share by Region</div>
                        <div className="da-viz-subtitle">Percentage distribution of total sales</div>
                      </div>
                    </div>
                    <MoreVertical size={16} style={{ color: 'var(--text-muted)', cursor: 'pointer' }} />
                  </div>

                  {/* Donut Chart with Legend */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '220px', padding: '0 0.5rem' }}>
                    {/* SVG Donut */}
                    <div style={{ position: 'relative', width: '160px', height: '160px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <svg width="160" height="160" viewBox="0 0 160 160">
                        {(() => {
                          const C = 2 * Math.PI * 55;
                          let acc = 0;
                          return (stats?.regions || []).map((item, idx) => {
                            const frac = (item.pct || 0) / 100;
                            const dash = frac * C;
                            const off = -acc * C;
                            acc += frac;
                            return (
                              <circle key={idx} cx="80" cy="80" r="55" fill="none" stroke={REGION_COLORS[idx % REGION_COLORS.length]} strokeWidth="26" strokeDasharray={`${dash} ${C - dash}`} strokeDashoffset={off} />
                            );
                          });
                        })()}
                      </svg>
                      <div style={{ position: 'absolute', textAlign: 'center' }}>
                        <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--text-headings)', fontFamily: 'var(--font-display)' }}>{stats ? fmtCompact(stats.totals.total_sales) : '—'}</div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontWeight: 600 }}>Total Sales</div>
                      </div>
                    </div>

                    {/* Donut Legend */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1, paddingLeft: '1.5rem' }}>
                      {(stats?.regions || []).map((item, idx) => (
                        <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '9px', height: '9px', borderRadius: '50%', background: REGION_COLORS[idx % REGION_COLORS.length] }} />
                            <span style={{ color: 'var(--text-secondary)' }}>{item.region}</span>
                          </div>
                          <span style={{ fontWeight: 700, color: 'var(--text-headings)' }}>{item.pct}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Lower Section: Regional Sales Details Table & Key Insights (Directly Matching Image 1) */}
              <div className="da-lower-grid">
                {/* Regional Sales Details Table */}
                <div className="da-viz-card" style={{ overflow: 'hidden' }}>
                  <div className="da-viz-header" style={{ marginBottom: '0.75rem' }}>
                    <div className="da-viz-title-group">
                      <FileSpreadsheet size={18} style={{ color: 'var(--copper-primary)' }} />
                      <div className="da-viz-title" style={{ fontSize: '0.96rem' }}>Regional Sales Details</div>
                    </div>
                    <button className="da-select-small" style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={exportRegionsCSV} disabled={!stats}>
                      <Download size={12} />
                      <span>Export CSV</span>
                    </button>
                  </div>

                  <div style={{ overflowX: 'auto' }}>
                    <table className="styled-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Region</th>
                          <th>Total Sales</th>
                          <th>Total Orders</th>
                          <th>Avg. Order Value</th>
                          <th>Customers</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(stats?.regions || []).map((row, idx) => (
                          <tr key={row.region}>
                            <td style={{ color: 'var(--text-muted)' }}>{idx + 1}</td>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: REGION_COLORS[idx % REGION_COLORS.length] }} />
                                <span>{row.region}</span>
                              </div>
                            </td>
                            <td style={{ fontWeight: 700, color: 'var(--text-headings)' }}>{fmtMoney(row.revenue)}</td>
                            <td>{fmtInt(row.orders)}</td>
                            <td>{fmtMoney(row.avg_order_value)}</td>
                            <td>{fmtInt(row.customers)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Key Insights Card (Directly Matching Image 1) */}
                <div className="da-viz-card">
                  <div className="da-viz-header" style={{ marginBottom: '0.5rem' }}>
                    <div className="da-viz-title-group">
                      <Lightbulb size={20} style={{ color: 'var(--copper-primary)' }} />
                      <div className="da-viz-title" style={{ fontSize: '0.96rem' }}>Key Insights</div>
                    </div>
                  </div>

                  <div className="da-insights-list">
                    {stats && stats.regions.length > 0 ? (() => {
                      const regs = stats.regions;
                      const top = regs[0];
                      const second = regs[1];
                      const topAov = [...regs].sort((a, b) => b.avg_order_value - a.avg_order_value)[0];
                      const topCat = stats.product_categories[0];
                      return (
                        <>
                          <div className="da-insight-item">
                            <div className="da-insight-num">1</div>
                            <div className="da-insight-text">
                              <strong>{top.region}</strong> region leads with <strong>{fmtMoney(top.revenue)}</strong> in sales (<strong>{top.pct}%</strong> of total).
                            </div>
                          </div>
                          {second && (
                            <div className="da-insight-item">
                              <div className="da-insight-num">2</div>
                              <div className="da-insight-text">
                                <strong>{second.region}</strong> region ranks second with <strong>{fmtMoney(second.revenue)}</strong> (<strong>{second.pct}%</strong> of total sales).
                              </div>
                            </div>
                          )}
                          <div className="da-insight-item">
                            <div className="da-insight-num copper">3</div>
                            <div className="da-insight-text">
                              Highest average order value is in <strong>{topAov.region} ({fmtMoney(topAov.avg_order_value)})</strong>.
                            </div>
                          </div>
                          {topCat && (
                            <div className="da-insight-item">
                              <div className="da-insight-num copper">4</div>
                              <div className="da-insight-text">
                                Top product category by revenue is <strong>{topCat.category}</strong> (<strong>{fmtMoney(topCat.revenue)}</strong>, {topCat.avg_margin_pct}% avg margin).
                              </div>
                            </div>
                          )}
                        </>
                      );
                    })() : (
                      <div style={{ padding: '1rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading live insights…</div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column: Schema Explorer, Recent Threads, Quick Examples (Matching Image 1) */}
            <div className="da-right-column">
              {/* Schema Explorer */}
              <div className="da-panel-card">
                <div className="da-panel-header">
                  <div className="da-panel-title">
                    <Database size={16} style={{ color: 'var(--teal-primary)' }} />
                    <span>Schema Explorer</span>
                  </div>
                  <span className="da-panel-link" onClick={() => setActiveTab('schema')}>
                    View All
                  </span>
                </div>

                <div style={{ position: 'relative', marginBottom: '10px' }}>
                  <Search size={13} style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }} />
                  <input
                    type="text"
                    placeholder="Search tables..."
                    value={schemaSearch}
                    onChange={(e) => setSchemaSearch(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 10px 7px 30px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-card)',
                      background: '#fbf9f5',
                      fontSize: '0.8rem',
                      outline: 'none'
                    }}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  {filteredTables.slice(0, 7).map((tbl, i) => (
                    <div 
                      key={i} 
                      className="da-table-nav-item"
                      onClick={() => handleRunQuery(`Show top 10 records from sales.${tbl.table_name}`)}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                        <Layers size={13} style={{ color: 'var(--teal-primary)' }} />
                        <span style={{ fontWeight: 500 }}>{tbl.table_name}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        <span>{tbl.row_count != null ? `${tbl.row_count} rows` : '—'}</span>
                        <ChevronRight size={12} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Recent Threads */}
              <div className="da-panel-card">
                <div className="da-panel-header">
                  <div className="da-panel-title">
                    <Clock size={16} style={{ color: 'var(--copper-primary)' }} />
                    <span>Recent Threads</span>
                  </div>
                  <span className="da-panel-link" onClick={() => setActiveTab('audit')}>
                    View All
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {cleanRecentThreads.map((item, idx) => (
                    <div 
                      key={idx} 
                      className="da-thread-history-item"
                      onClick={() => handleRunQuery(item.question || item.natural_language_query)}
                    >
                      <MessageSquare size={13} style={{ color: 'var(--teal-primary)', marginTop: '2px', flexShrink: 0 }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-headings)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.question || item.natural_language_query}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {item.time || 'Recently executed'}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Quick Examples */}
              <div className="da-panel-card">
                <div className="da-panel-header">
                  <div className="da-panel-title">
                    <Sparkles size={16} style={{ color: 'var(--copper-primary)' }} />
                    <span>Quick Examples</span>
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {[
                    "Total sales by region",
                    "Top 5 customers",
                    "Highest revenue products",
                    "Monthly sales trend"
                  ].map((ex, i) => (
                    <button
                      key={i}
                      className="da-quick-example-btn"
                      onClick={() => handleRunQuery(ex)}
                    >
                      <span>{ex}</span>
                      <ArrowRight size={13} />
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* VIEW 2: Schema Catalog Tab */}
        {/* VIEW 1b: Discover & Early Warnings */}
        {activeTab === 'discover' && (
          <div className="da-view-container">
            <DiscoverView onExploreFurther={(q) => { setActiveTab('workspace'); handleRunQuery(q); }} onOpenInvestigation={handleOpenInvestigation} onSimulate={handleSimulateFinding} />
          </div>
        )}

        {/* VIEW 1c: Investigation Workspace */}
        {activeTab === 'investigations' && (
          <div className="da-view-container">
            <InvestigationView currentRole={currentRole} focusId={investigationFocusId} />
          </div>
        )}

        {/* VIEW 1d: What-If Decision Simulator */}
        {activeTab === 'simulator' && (
          <div className="da-view-container">
            <ScenarioSimulatorView currentRole={currentRole} focusFindingId={scenarioFocusFindingId} onOpenInvestigation={navigateToInvestigation} />
          </div>
        )}

        {/* VIEW 1e: Personalized Executive Briefings */}
        {activeTab === 'briefings' && (
          <div className="da-view-container">
            <BriefingInboxView currentRole={currentRole} onOpenInvestigation={handleOpenInvestigation} />
          </div>
        )}

        {/* VIEW 1f: Cross-System Intelligence */}
        {activeTab === 'datasources' && (
          <div className="da-view-container">
            <DataSourcesView currentRole={currentRole} />
          </div>
        )}

        {activeTab === 'schema' && (
          <div className="da-view-container">
            <SchemaBrowser onSelectTableQuery={(q) => { setActiveTab('workspace'); handleRunQuery(q); }} />
          </div>
        )}

        {/* VIEW 3: Benchmark Runner Tab */}
        {activeTab === 'benchmark' && (
          <div className="da-view-container">
            <BenchmarkRunner />
          </div>
        )}

        {/* VIEW 4: 35-Case Adversarial Security Suite */}
        {activeTab === 'security' && (
          <div className="da-view-container">
            <SecurityEvaluationView />
          </div>
        )}

        {/* VIEW 5: 50 Conversations Multi-Turn Evaluation */}
        {activeTab === 'conversations' && (
          <div className="da-view-container">
            <ConversationsEvaluationView />
          </div>
        )}

        {/* VIEW 6: Dynamic Schema Drift Recovery */}
        {activeTab === 'schema_recovery' && (
          <div className="da-view-container">
            <SchemaRecoveryView />
          </div>
        )}

        {/* VIEW 7: QueryPilot Chaos Arena */}
        {activeTab === 'chaos' && (
          <div className="da-view-container">
            <ChaosArenaView />
          </div>
        )}

        {/* VIEW 8: Audit Log Tab */}
        {activeTab === 'audit' && (
          <div className="da-view-container">
            <AuditLog />
          </div>
        )}

        {/* VIEW 9: Executive Reports Tab */}
        {activeTab === 'reports' && (
          <div className="da-view-container">
            <ReportsView />
          </div>
        )}

        {/* VIEW 10: System Configuration & Security Settings */}
        {activeTab === 'settings' && (
          <div className="da-view-container">
            <SettingsView 
              currentRole={currentRole} 
              onRoleChange={setCurrentRole} 
              theme={theme} 
              onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} 
            />
          </div>
        )}
      </div>
    </div>
  );
}
