import React, { useState, useEffect, useRef } from 'react';
import { 
  Flame, ShieldAlert, AlertTriangle, Bug, Terminal, Database, 
  CheckCircle2, XCircle, Clock, Play, RotateCcw, ChevronDown, 
  ChevronRight, RefreshCw, Layers, Cpu, ArrowRight, ShieldCheck, 
  HelpCircle, Zap, Activity, Info
} from 'lucide-react';

const SEVERITY_COLORS = {
  CRITICAL: { bg: 'rgba(239, 68, 68, 0.15)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.3)' },
  HIGH: { bg: 'rgba(249, 115, 22, 0.15)', text: '#f97316', border: 'rgba(249, 115, 22, 0.3)' },
  MEDIUM: { bg: 'rgba(234, 179, 8, 0.15)', text: '#eab308', border: 'rgba(234, 179, 8, 0.3)' },
  LOW: { bg: 'rgba(59, 130, 246, 0.15)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.3)' },
};

const OUTCOME_CONFIG = {
  verified_recovered: {
    label: 'Recovered & Verified',
    desc: 'Candidate query synthesized, executed safely, and verified against ground truth.',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.12)',
    border: 'rgba(16, 185, 129, 0.3)',
    icon: CheckCircle2,
  },
  executed_uncertain: {
    label: 'Executed (Uncertain Match)',
    desc: 'Query executed successfully, but independent semantic verification is partial or divergent.',
    color: '#eab308',
    bg: 'rgba(234, 179, 8, 0.12)',
    border: 'rgba(234, 179, 8, 0.3)',
    icon: AlertTriangle,
  },
  correctly_abstained_clarified: {
    label: 'Correctly Abstained / Clarified',
    desc: 'Agent detected ambiguity or conflicting definitions and requested clarification without hallucinating.',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.12)',
    border: 'rgba(56, 189, 248, 0.3)',
    icon: HelpCircle,
  },
  recovery_failed: {
    label: 'Recovery Failed',
    desc: 'Agent was unable to overcome fault or recovery candidate produced an execution error.',
    color: '#f43f5e',
    bg: 'rgba(244, 63, 94, 0.12)',
    border: 'rgba(244, 63, 94, 0.3)',
    icon: XCircle,
  },
  security_violation_detected: {
    label: 'Security Boundary Enforced',
    desc: 'Injected hostile payload caught and quarantined; prohibited operations blocked.',
    color: '#a855f7',
    bg: 'rgba(168, 85, 247, 0.12)',
    border: 'rgba(168, 85, 247, 0.3)',
    icon: ShieldCheck,
  },
  setup_failed: {
    label: 'Setup Error',
    desc: 'Challenge preparation or sandbox cloning failed.',
    color: '#ef4444',
    bg: 'rgba(239, 68, 68, 0.12)',
    border: 'rgba(239, 68, 68, 0.3)',
    icon: AlertTriangle,
  },
};

export default function ChaosArenaView() {
  const [challenges, setChallenges] = useState([]);
  const [selectedChallengeId, setSelectedChallengeId] = useState('duplicate_keys');
  const [selectedQuestion, setSelectedQuestion] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState(null);
  const [runData, setRunData] = useState(null);
  const [expandedStages, setExpandedStages] = useState({ 0: false, 1: false, 2: false, 3: true, 4: true, 5: true, 6: true, 7: true });
  const [resettingEnv, setResettingEnv] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [recentRuns, setRecentRuns] = useState([]);

  const pollIntervalRef = useRef(null);

  // Load challenges and recent runs on mount
  useEffect(() => {
    fetchChallenges();
    fetchRecentRuns();
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const fetchChallenges = async () => {
    try {
      const res = await fetch('/api/v1/chaos/challenges');
      if (res.ok) {
        const data = await res.json();
        setChallenges(data);
        if (data.length > 0 && !selectedQuestion) {
          const defaultC = data.find(c => c.id === 'duplicate_keys') || data[0];
          setSelectedChallengeId(defaultC.id);
          setSelectedQuestion(defaultC.default_question);
        }
      }
    } catch (e) {
      console.error('Failed to load chaos challenges:', e);
    }
  };

  const fetchRecentRuns = async () => {
    try {
      const res = await fetch('/api/v1/chaos/runs');
      if (res.ok) {
        const data = await res.json();
        setRecentRuns(data);
        if (data.length > 0 && !runData) {
          setRunData(data[0]);
          setActiveRunId(data[0].run_id);
        }
      }
    } catch (e) {
      console.warn('Failed to load recent chaos runs:', e);
    }
  };

  const currentChallenge = challenges.find(c => c.id === selectedChallengeId) || challenges[0] || {};

  const handleSelectChallenge = (cId) => {
    setSelectedChallengeId(cId);
    const c = challenges.find(item => item.id === cId);
    if (c) {
      setSelectedQuestion(c.default_question);
    }
  };

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleResetSandbox = async () => {
    setResettingEnv(true);
    try {
      const res = await fetch('/api/v1/chaos/reset', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast('Sandbox reset successfully: chaos_test schema recloned from sales.');
      } else {
        showToast(`Reset error: ${data.error}`);
      }
    } catch (e) {
      showToast('Failed to connect to reset endpoint.');
    } finally {
      setResettingEnv(false);
    }
  };

  const handleStartRun = async () => {
    if (isRunning) return;
    setIsRunning(true);
    setRunData(null);

    try {
      const res = await fetch('/api/v1/chaos/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          challenge_id: selectedChallengeId,
          question: selectedQuestion,
          sync: true, // Execute full run and receive verified result
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setRunData(data);
        setActiveRunId(data.run_id);
        fetchRecentRuns();
        showToast(`Challenge executed: ${data.outcome_category}`);
      } else {
        const err = await res.json();
        showToast(`Run failed: ${err.detail || 'Server error'}`);
      }
    } catch (e) {
      showToast(`Connection error: ${e.message}`);
    } finally {
      setIsRunning(false);
    }
  };

  const handleCancelRun = async () => {
    if (!activeRunId) return;
    try {
      await fetch(`/api/v1/chaos/runs/${activeRunId}/cancel`, { method: 'POST' });
      showToast('Cancellation request sent.');
      setIsRunning(false);
    } catch (e) {
      console.error(e);
    }
  };

  const toggleStage = (idx) => {
    setExpandedStages(p => ({ ...p, [idx]: !p[idx] }));
  };

  const outcomeConfig = runData?.outcome_category ? OUTCOME_CONFIG[runData.outcome_category] || OUTCOME_CONFIG.executed_uncertain : null;
  const OutcomeIcon = outcomeConfig?.icon || Activity;

  return (
    <div style={{ padding: '24px 32px', color: 'var(--text-primary)', maxWidth: '1440px', margin: '0 auto' }}>
      {/* Toast alert */}
      {toastMessage && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '24px',
          background: 'rgba(26, 29, 38, 0.95)',
          border: '1px solid #ff6b00',
          boxShadow: '0 8px 24px rgba(255, 107, 0, 0.25)',
          color: '#ff8533',
          padding: '12px 20px',
          borderRadius: '8px',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '13px',
          fontWeight: 600,
        }}>
          <Flame size={16} color="#ff6b00" />
          {toastMessage}
        </div>
      )}

      {/* Header Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(255, 107, 0, 0.12) 0%, rgba(22, 25, 34, 0.95) 100%)',
        border: '1px solid rgba(255, 107, 0, 0.3)',
        borderRadius: '12px',
        padding: '24px 28px',
        marginBottom: '28px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '20px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '48px',
            height: '48px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #ff6b00 0%, #d9480f 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 16px rgba(255, 107, 0, 0.4)',
          }}>
            <Flame size={26} color="#fff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.02em' }}>
                QueryPilot Chaos Arena
              </h1>
              <span style={{
                background: 'rgba(255, 107, 0, 0.2)',
                color: '#ff8533',
                border: '1px solid rgba(255, 107, 0, 0.4)',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}>
                Live Adversarial Testbed
              </span>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: '13px', color: '#94a3b8', maxWidth: '640px' }}>
              Inject real-world schema drift, duplicate join fanouts, and adversarial payloads into an isolated PostgreSQL sandbox. Watch the agent detect, profile, repair, and independently verify recovery in real time.
            </p>
          </div>
        </div>

        {/* Global Sandbox Reset & Health */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={handleResetSandbox}
            disabled={resettingEnv || isRunning}
            style={{
              background: 'rgba(30, 41, 59, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              color: '#cbd5e1',
              padding: '10px 16px',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              cursor: resettingEnv || isRunning ? 'not-allowed' : 'pointer',
              transition: 'all 0.2s ease',
            }}
            title="Reclone clean isolated chaos_test schema from sales"
          >
            <RotateCcw size={15} className={resettingEnv ? 'spin' : ''} color="#ff8533" />
            {resettingEnv ? 'Resetting Sandbox...' : 'Reset Isolated Sandbox'}
          </button>
        </div>
      </div>

      {/* Grid Layout: Challenge Selection & Controls (Left) + Live Timeline & Proof (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '24px' }}>
        
        {/* Left Column: Challenge Selector & Judge Controls */}
        <div>
          {/* Challenge Selector */}
          <div style={{
            background: '#161922',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '12px',
            padding: '20px',
            marginBottom: '20px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
              <Bug size={16} color="#ff8533" />
              <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f1f5f9', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                1. Select Adversarial Challenge
              </h2>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {challenges.map((c) => {
                const isSelected = c.id === selectedChallengeId;
                const sev = SEVERITY_COLORS[c.severity] || SEVERITY_COLORS.HIGH;
                return (
                  <div
                    key={c.id}
                    onClick={() => handleSelectChallenge(c.id)}
                    style={{
                      background: isSelected ? 'rgba(255, 107, 0, 0.08)' : 'rgba(30, 41, 59, 0.3)',
                      border: isSelected ? '1px solid #ff6b00' : '1px solid rgba(255, 255, 255, 0.06)',
                      borderRadius: '8px',
                      padding: '12px 14px',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: isSelected ? '#ff8533' : '#f1f5f9' }}>
                        {c.title}
                      </span>
                      <span style={{
                        background: sev.bg,
                        color: sev.text,
                        border: `1px solid ${sev.border}`,
                        fontSize: '10px',
                        fontWeight: 700,
                        padding: '1px 6px',
                        borderRadius: '3px',
                      }}>
                        {c.severity}
                      </span>
                    </div>
                    <p style={{ margin: 0, fontSize: '11px', color: '#94a3b8', lineHeight: 1.4 }}>
                      {c.description}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Judge Controls & Question Configuration */}
          <div style={{
            background: '#161922',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '12px',
            padding: '20px',
            marginBottom: '20px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
              <Terminal size={16} color="#ff8533" />
              <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f1f5f9', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                2. Test Question & Dispatch
              </h2>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '6px', fontWeight: 600 }}>
                SUPPORTED BENCHMARK PROMPT:
              </label>
              <select
                value={selectedQuestion}
                onChange={(e) => setSelectedQuestion(e.target.value)}
                style={{
                  width: '100%',
                  background: '#0e1017',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  padding: '9px 12px',
                  fontSize: '12px',
                  outline: 'none',
                  cursor: 'pointer',
                }}
              >
                {(currentChallenge.supported_questions || [currentChallenge.default_question]).map((q, idx) => (
                  <option key={idx} value={q}>{q}</option>
                ))}
              </select>
            </div>

            <div style={{
              background: 'rgba(14, 16, 23, 0.6)',
              border: '1px dashed rgba(255, 107, 0, 0.25)',
              borderRadius: '6px',
              padding: '10px 12px',
              marginBottom: '18px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <Info size={13} color="#ff8533" />
                <span style={{ fontSize: '11px', fontWeight: 700, color: '#ff8533' }}>FAULT SPECIFICATION</span>
              </div>
              <p style={{ margin: 0, fontSize: '11px', color: '#94a3b8', lineHeight: 1.4 }}>
                {currentChallenge.fault_description}
              </p>
            </div>

            {/* Run Challenge Actions */}
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                onClick={handleStartRun}
                disabled={isRunning}
                style={{
                  flex: 1,
                  background: isRunning ? 'rgba(255, 107, 0, 0.4)' : 'linear-gradient(135deg, #ff6b00 0%, #ea580c 100%)',
                  border: 'none',
                  color: '#ffffff',
                  padding: '12px 18px',
                  borderRadius: '8px',
                  fontSize: '13px',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  cursor: isRunning ? 'not-allowed' : 'pointer',
                  boxShadow: '0 4px 14px rgba(255, 107, 0, 0.35)',
                  transition: 'all 0.15s ease',
                }}
              >
                <Play size={15} fill="#fff" />
                {isRunning ? 'Injecting & Recovering...' : 'Run Challenge'}
              </button>

              {isRunning && (
                <button
                  onClick={handleCancelRun}
                  style={{
                    background: 'rgba(239, 68, 68, 0.2)',
                    border: '1px solid rgba(239, 68, 68, 0.4)',
                    color: '#ef4444',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              )}
            </div>
          </div>

          {/* Recent Arena Runs History */}
          <div style={{
            background: '#161922',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '12px',
            padding: '18px 20px',
          }}>
            <h3 style={{ margin: '0 0 12px', fontSize: '12px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Recent Arena Executions
            </h3>
            {recentRuns.length === 0 ? (
              <p style={{ margin: 0, fontSize: '11px', color: '#64748b' }}>No past challenge executions yet.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {recentRuns.slice(0, 5).map((r) => {
                  const outConf = OUTCOME_CONFIG[r.outcome_category] || OUTCOME_CONFIG.executed_uncertain;
                  return (
                    <div
                      key={r.run_id}
                      onClick={() => {
                        setRunData(r);
                        setActiveRunId(r.run_id);
                        setSelectedChallengeId(r.challenge_id);
                      }}
                      style={{
                        padding: '8px 10px',
                        background: r.run_id === activeRunId ? 'rgba(255, 107, 0, 0.1)' : 'rgba(14, 16, 23, 0.5)',
                        border: r.run_id === activeRunId ? '1px solid #ff6b00' : '1px solid rgba(255, 255, 255, 0.04)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>{r.challenge_title}</div>
                        <div style={{ fontSize: '10px', color: '#64748b' }}>{r.run_id.split('_').slice(1).join('_')}</div>
                      </div>
                      <span style={{
                        fontSize: '10px',
                        fontWeight: 700,
                        color: outConf.color,
                        background: outConf.bg,
                        padding: '2px 6px',
                        borderRadius: '3px',
                      }}>
                        {r.verification_match ? 'VERIFIED' : r.outcome_category.split('_')[0].toUpperCase()}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Live 8-Stage Timeline + Before-and-After Evidence */}
        <div>
          {/* Outcome Status Banner */}
          {runData && (
            <div style={{
              background: outcomeConfig?.bg || '#161922',
              border: `1px solid ${outcomeConfig?.border || 'rgba(255, 255, 255, 0.1)'}`,
              borderRadius: '12px',
              padding: '18px 24px',
              marginBottom: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '16px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                <div style={{
                  width: '38px',
                  height: '38px',
                  borderRadius: '8px',
                  background: outcomeConfig?.color || '#ff6b00',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <OutcomeIcon size={22} color="#0e1017" />
                </div>
                <div>
                  <div style={{ fontSize: '16px', fontWeight: 700, color: outcomeConfig?.color || '#f8fafc' }}>
                    {outcomeConfig?.label || runData.outcome_category}
                  </div>
                  <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '2px' }}>
                    {outcomeConfig?.desc}
                  </div>
                </div>
              </div>

              {/* Execution Latencies & Match Status */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Total Duration</div>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: '#f8fafc' }}>{runData.total_duration_ms} ms</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Detection</div>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: '#ff8533' }}>{runData.detection_latency_ms} ms</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Semantic Match</div>
                  <div style={{
                    fontSize: '13px',
                    fontWeight: 700,
                    color: runData.verification_match ? '#10b981' : '#f43f5e',
                  }}>
                    {runData.verification_match ? '100% MATCH' : 'DIVERGENT'}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 8-Stage Execution Timeline */}
          <div style={{
            background: '#161922',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '12px',
            padding: '20px 24px',
            marginBottom: '24px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Activity size={16} color="#ff6b00" />
                <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f1f5f9', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Live Execution & Recovery Timeline (8 Stages)
                </h2>
              </div>
              <span style={{ fontSize: '11px', color: '#64748b' }}>
                {runData ? `Run ID: ${runData.run_id}` : 'Awaiting Run Dispatch'}
              </span>
            </div>

            {/* Stages Stack */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {(runData?.stages || [
                { name: '1. Challenge Preparation', status: 'pending', summary: 'Cloning pristine dataset into isolated chaos_test sandbox' },
                { name: '2. Baseline Question Execution', status: 'pending', summary: 'Executing baseline question against clean dataset' },
                { name: '3. Fault Injection', status: 'pending', summary: 'Applying controlled deterministic fault to sandbox' },
                { name: '4. Failure Detection', status: 'pending', summary: 'Detecting execution errors or Cartesian aggregate inflation' },
                { name: '5. Diagnostic Investigation', status: 'pending', summary: 'Profiling schema drift and primary/foreign key integrity' },
                { name: '6. Recovery Attempt', status: 'pending', summary: 'Synthesizing recovery SQL with CTE deduplication / adapted identifiers' },
                { name: '7. Independent Result Verification', status: 'pending', summary: 'Comparing recovery output against ground truth query' },
                { name: '8. Final Outcome Classification', status: 'pending', summary: 'Classifying verified recovery, abstention, or failure' },
              ]).map((st, idx) => {
                const isExpanded = expandedStages[idx];
                const isDone = st.status === 'completed';
                const isFail = st.status === 'failed';
                const isRunningStage = st.status === 'running';

                let badgeColor = '#64748b';
                let badgeBg = 'rgba(100, 116, 139, 0.15)';
                if (isDone) { badgeColor = '#10b981'; badgeBg = 'rgba(16, 185, 129, 0.15)'; }
                else if (isFail) { badgeColor = '#ef4444'; badgeBg = 'rgba(239, 68, 68, 0.15)'; }
                else if (isRunningStage) { badgeColor = '#ff8533'; badgeBg = 'rgba(255, 107, 0, 0.15)'; }

                return (
                  <div
                    key={idx}
                    style={{
                      background: 'rgba(14, 16, 23, 0.6)',
                      border: isRunningStage ? '1px solid #ff6b00' : '1px solid rgba(255, 255, 255, 0.05)',
                      borderRadius: '8px',
                      overflow: 'hidden',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <div
                      onClick={() => toggleStage(idx)}
                      style={{
                        padding: '12px 16px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        cursor: 'pointer',
                        userSelect: 'none',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {isDone ? (
                          <CheckCircle2 size={16} color="#10b981" />
                        ) : isFail ? (
                          <XCircle size={16} color="#ef4444" />
                        ) : isRunningStage ? (
                          <RefreshCw size={16} color="#ff8533" className="spin" />
                        ) : (
                          <Clock size={16} color="#64748b" />
                        )}
                        <div>
                          <span style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                            {st.name}
                          </span>
                          <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: '12px' }}>
                            {st.summary}
                          </span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {st.duration_ms > 0 && (
                          <span style={{ fontSize: '11px', color: '#64748b' }}>
                            {st.duration_ms} ms
                          </span>
                        )}
                        <span style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          color: badgeColor,
                          background: badgeBg,
                          padding: '2px 6px',
                          borderRadius: '3px',
                          textTransform: 'uppercase',
                        }}>
                          {st.status}
                        </span>
                        {isExpanded ? <ChevronDown size={14} color="#64748b" /> : <ChevronRight size={14} color="#64748b" />}
                      </div>
                    </div>

                    {/* Expandable Technical Details */}
                    {isExpanded && st.details && Object.keys(st.details).length > 0 && (
                      <div style={{
                        padding: '12px 16px',
                        background: '#090a0f',
                        borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                        fontSize: '12px',
                        fontFamily: 'monospace',
                        color: '#cbd5e1',
                      }}>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                          {JSON.stringify(st.details, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Before-and-After Comparison Panel */}
          {runData && (
            <div style={{
              background: '#161922',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '20px 24px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '18px' }}>
                <Layers size={16} color="#ff6b00" />
                <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f1f5f9', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Before-and-After Forensic Evidence
                </h2>
              </div>

              {/* Side by side comparison: Baseline vs Recovery SQL */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
                {/* Baseline Column */}
                <div style={{
                  background: '#0e1017',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  borderRadius: '8px',
                  padding: '14px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
                      Baseline Query (Pristine Schema)
                    </span>
                    <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 600 }}>
                      {runData.baseline_row_count} rows
                    </span>
                  </div>
                  <pre style={{
                    margin: 0,
                    padding: '10px',
                    background: '#07080c',
                    borderRadius: '6px',
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    color: '#93c5fd',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    maxHeight: '120px',
                    overflowY: 'auto',
                  }}>
                    {runData.baseline_sql || '-- None'}
                  </pre>
                </div>

                {/* Recovery Column */}
                <div style={{
                  background: '#0e1017',
                  border: '1px solid rgba(255, 107, 0, 0.3)',
                  borderRadius: '8px',
                  padding: '14px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 700, color: '#ff8533', textTransform: 'uppercase' }}>
                      Recovery Query (Mutated Sandbox)
                    </span>
                    <span style={{ fontSize: '11px', color: '#ff8533', fontWeight: 600 }}>
                      {runData.recovery_row_count} rows
                    </span>
                  </div>
                  <pre style={{
                    margin: 0,
                    padding: '10px',
                    background: '#07080c',
                    borderRadius: '6px',
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    color: '#fdba74',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    maxHeight: '120px',
                    overflowY: 'auto',
                  }}>
                    {runData.recovery_sql || '-- None'}
                  </pre>
                </div>
              </div>

              {/* Data Sample Comparison */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <div style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8', marginBottom: '6px' }}>
                    BASELINE ROWS (SAMPLE):
                  </div>
                  <div style={{
                    background: '#090a0f',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '6px',
                    padding: '10px',
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    color: '#cbd5e1',
                    maxHeight: '160px',
                    overflowY: 'auto',
                  }}>
                    {runData.baseline_rows && runData.baseline_rows.length > 0 ? (
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', textAlign: 'left', color: '#64748b' }}>
                            {Object.keys(runData.baseline_rows[0] || {}).map((k) => (
                              <th key={k} style={{ padding: '4px 6px' }}>{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {runData.baseline_rows.slice(0, 4).map((row, rIdx) => (
                            <tr key={rIdx} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.03)' }}>
                              {Object.values(row).map((v, cIdx) => (
                                <td key={cIdx} style={{ padding: '4px 6px' }}>{String(v)}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      'No rows.'
                    )}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '11px', fontWeight: 600, color: '#ff8533', marginBottom: '6px' }}>
                    RECOVERED ROWS (VERIFIED):
                  </div>
                  <div style={{
                    background: '#090a0f',
                    border: '1px solid rgba(255, 107, 0, 0.2)',
                    borderRadius: '6px',
                    padding: '10px',
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    color: '#fed7aa',
                    maxHeight: '160px',
                    overflowY: 'auto',
                  }}>
                    {runData.recovery_rows && runData.recovery_rows.length > 0 ? (
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', textAlign: 'left', color: '#ea580c' }}>
                            {Object.keys(runData.recovery_rows[0] || {}).map((k) => (
                              <th key={k} style={{ padding: '4px 6px' }}>{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {runData.recovery_rows.slice(0, 4).map((row, rIdx) => (
                            <tr key={rIdx} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.03)' }}>
                              {Object.values(row).map((v, cIdx) => (
                                <td key={cIdx} style={{ padding: '4px 6px' }}>{String(v)}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      'No rows.'
                    )}
                  </div>
                </div>
              </div>

              {/* Verification Proof Summary */}
              <div style={{
                marginTop: '16px',
                padding: '12px 14px',
                background: runData.verification_match ? 'rgba(16, 185, 129, 0.08)' : 'rgba(234, 179, 8, 0.08)',
                border: `1px solid ${runData.verification_match ? 'rgba(16, 185, 129, 0.3)' : 'rgba(234, 179, 8, 0.3)'}`,
                borderRadius: '8px',
                fontSize: '12px',
                color: runData.verification_match ? '#34d399' : '#fde047',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
              }}>
                <ShieldCheck size={18} />
                <span>
                  <strong>Independent Verification Proof:</strong> {runData.verification_evidence}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
