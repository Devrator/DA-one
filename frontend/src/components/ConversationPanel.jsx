import React from 'react';
import { MessageSquare, Plus, CheckCircle2, AlertCircle, ArrowRight, CornerDownRight, Tag } from 'lucide-react';

export default function ConversationPanel({
  currentSessionId,
  turns = [],
  onNewSession,
  onSelectTurnQuery,
  userRole = 'executive',
  activeContext = {},
}) {
  return (
    <div style={{
      background: 'rgba(15, 23, 42, 0.6)',
      border: '1px solid rgba(51, 65, 85, 0.5)',
      borderRadius: '10px',
      padding: '14px 16px',
      marginBottom: '16px',
    }}>
      {/* Session Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{
            width: '28px',
            height: '28px',
            borderRadius: '6px',
            background: 'rgba(56, 189, 248, 0.15)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#38bdf8'
          }}>
            <MessageSquare size={15} />
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>Multi-Turn Conversation Thread</span>
              <span style={{
                fontSize: '10px',
                padding: '1px 6px',
                borderRadius: '4px',
                background: 'rgba(56, 189, 248, 0.1)',
                color: '#38bdf8',
                border: '1px solid rgba(56, 189, 248, 0.2)'
              }}>
                {turns.length} / 3 Turns
              </span>
            </div>
            <div style={{ fontSize: '11px', color: '#64748b' }}>
              Persistent Session Context ({currentSessionId || 'Active'}) &bull; Scoped to {userRole}
            </div>
          </div>
        </div>

        <button
          onClick={onNewSession}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '5px 10px',
            borderRadius: '6px',
            background: 'rgba(51, 65, 85, 0.4)',
            border: '1px solid rgba(71, 85, 105, 0.5)',
            color: '#cbd5e1',
            fontSize: '11px',
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
        >
          <Plus size={13} />
          New Thread
        </button>
      </div>

      {/* Structured Context Tags */}
      {turns.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px' }}>
          {activeContext.metric && (
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '4px',
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              color: '#34d399',
            }}>
              <Tag size={10} /> Metric: {activeContext.metric}
            </span>
          )}
          {activeContext.grouping && (
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '4px',
              background: 'rgba(56, 189, 248, 0.1)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              color: '#38bdf8',
            }}>
              <Tag size={10} /> Grouping: {activeContext.grouping}
            </span>
          )}
          {activeContext.filter && (
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '4px',
              background: 'rgba(251, 191, 36, 0.1)',
              border: '1px solid rgba(251, 191, 36, 0.3)',
              color: '#fbbf24',
            }}>
              <Tag size={10} /> Filter: {activeContext.filter}
            </span>
          )}
        </div>
      )}

      {/* Turns Timeline */}
      {turns.length === 0 ? (
        <div style={{
          padding: '12px',
          borderRadius: '6px',
          background: 'rgba(15, 23, 42, 0.4)',
          border: '1px dashed rgba(51, 65, 85, 0.4)',
          fontSize: '12px',
          color: '#64748b',
          textAlign: 'center',
        }}>
          Ask a question below to start Turn 1. Follow-up questions (e.g. "Now only for 2023", "Compare with 2022") preserve context automatically.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {turns.map((t, idx) => {
            const isLatest = idx === turns.length - 1;
            const isClarification = t.status === 'clarification_needed';
            return (
              <div 
                key={t.id || idx}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  background: isLatest ? 'rgba(30, 41, 59, 0.6)' : 'rgba(15, 23, 42, 0.4)',
                  border: isLatest ? '1px solid rgba(56, 189, 248, 0.3)' : '1px solid rgba(51, 65, 85, 0.3)',
                }}
              >
                <div style={{
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 700,
                  background: isClarification ? 'rgba(251, 191, 36, 0.2)' : 'rgba(56, 189, 248, 0.15)',
                  color: isClarification ? '#fbbf24' : '#38bdf8',
                  marginTop: '1px',
                }}>
                  Turn {idx + 1}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9', marginBottom: '2px' }}>
                    {t.question}
                  </div>
                  {isClarification ? (
                    <div style={{ fontSize: '11px', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <AlertCircle size={11} /> Clarification requested: {t.clarification_message}
                    </div>
                  ) : (
                    <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '2px' }}>
                        <CheckCircle2 size={11} /> {t.result_row_count ?? 0} rows
                      </span>
                      <span>&bull;</span>
                      <span>{t.execution_time_ms ? `${Math.round(t.execution_time_ms)}ms` : ''}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
