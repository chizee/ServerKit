import React from 'react';

export function StatsGrid({ children, className = '' }) {
    return <div className={`stats-grid ${className}`.trim()}>{children}</div>;
}

export function StatCard({
    icon: Icon,
    iconVariant,
    iconNode,
    label,
    value,
    suffix,
    valueClassName = '',
    children,
}) {
    const iconClass = ['stat-icon', iconVariant].filter(Boolean).join(' ');
    return (
        <div className="stat-card">
            <div className={iconClass}>
                {iconNode ?? (Icon ? <Icon size={20} /> : null)}
            </div>
            <div className="stat-content">
                <span className="stat-label">{label}</span>
                {children ?? (
                    <span className={`stat-value ${valueClassName}`.trim()}>
                        {value}
                        {suffix && <span className="stat-suffix">{suffix}</span>}
                    </span>
                )}
            </div>
        </div>
    );
}

export default StatCard;
