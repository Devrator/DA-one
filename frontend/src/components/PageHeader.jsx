import React from 'react';

/**
 * Standardized executive page header banner for all views in DA-ONE.
 * Provides unified branding, clear titles, subtitles, status tags, and action buttons.
 */
export default function PageHeader({
  icon: Icon,
  title,
  subtitle,
  badge,
  badgeType = 'teal',
  actions = null,
  stats = null
}) {
  const getBadgeStyle = () => {
    switch (badgeType) {
      case 'copper':
        return {
          background: 'rgba(194, 120, 71, 0.12)',
          border: '1px solid rgba(194, 120, 71, 0.3)',
          color: 'var(--copper-primary)'
        };
      case 'emerald':
      case 'success':
        return {
          background: 'rgba(16, 185, 129, 0.12)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          color: '#10b981'
        };
      case 'amber':
      case 'warning':
        return {
          background: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          color: '#f59e0b'
        };
      case 'purple':
        return {
          background: 'rgba(168, 85, 247, 0.12)',
          border: '1px solid rgba(168, 85, 247, 0.3)',
          color: '#a855f7'
        };
      case 'sky':
      case 'info':
        return {
          background: 'rgba(56, 189, 248, 0.12)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          color: '#38bdf8'
        };
      default:
        return {
          background: 'rgba(20, 184, 166, 0.12)',
          border: '1px solid rgba(20, 184, 166, 0.3)',
          color: 'var(--teal-primary)'
        };
    }
  };

  return (
    <div className="da-screen-header">
      <div className="da-screen-header-left">
        {Icon && (
          <div className="da-screen-icon-box">
            <Icon size={24} />
          </div>
        )}
        <div className="da-screen-title-group">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h1 className="da-screen-title">{title}</h1>
            {badge && (
              <span className="da-screen-badge" style={getBadgeStyle()}>
                {badge}
              </span>
            )}
          </div>
          {subtitle && <p className="da-screen-subtitle">{subtitle}</p>}
        </div>
      </div>

      {actions && (
        <div className="da-screen-header-right">
          {actions}
        </div>
      )}

      {stats && (
        <div className="da-screen-stats-strip">
          {stats}
        </div>
      )}
    </div>
  );
}
