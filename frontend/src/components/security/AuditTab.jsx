import React, { useState } from 'react';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

const AuditTab = () => {
    const [audit, setAudit] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const runAudit = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await api.generateSecurityAudit();
            setAudit(data.audit);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const getSeverityVariant = (severity) => {
        switch (severity) {
            case 'pass': return 'success';
            case 'critical': return 'destructive';
            case 'warning': return 'warning';
            case 'info': return 'info';
            default: return 'secondary';
        }
    };

    const getScoreClass = (score) => {
        if (score >= 80) return 'score-excellent';
        if (score >= 60) return 'score-good';
        if (score >= 40) return 'score-fair';
        return 'score-poor';
    };

    return (
        <div className="audit-tab">
            <div className="card">
                <div className="card-header">
                    <h3>Security Audit</h3>
                    <Button variant="default" onClick={runAudit} disabled={loading}>
                        {loading ? 'Running Audit...' : 'Run Audit'}
                    </Button>
                </div>
                <div className="card-body">
                    {error && <div className="alert alert-danger">{error}</div>}

                    {!audit && !loading && (
                        <div className="empty-state">
                            <svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" fill="none" strokeWidth="1">
                                <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                            </svg>
                            <p>Run a security audit to check your server&apos;s configuration.</p>
                        </div>
                    )}

                    {loading && (
                        <div className="loading-state">
                            <div className="spinner"></div>
                            <p>Running security audit...</p>
                        </div>
                    )}

                    {audit && !loading && (
                        <div className="audit-results">
                            <div className={`audit-score ${getScoreClass(audit.score)}`}>
                                <span className="score-value">{audit.score}</span>
                                <span className="score-label">Security Score</span>
                            </div>

                            <div className="audit-timestamp">
                                Generated: {new Date(audit.generated_at).toLocaleString()}
                            </div>

                            {Object.entries(audit.services || {}).map(([service, data]) => (
                                <div key={service} className="audit-section">
                                    <h4>{service.toUpperCase()}</h4>
                                    <div className="findings-list">
                                        {data.findings?.map((finding, idx) => (
                                            <div key={idx} className="finding-item">
                                                <Badge variant={getSeverityVariant(finding.severity)}>
                                                    {finding.severity}
                                                </Badge>
                                                <span className="finding-message">{finding.message}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}

                            {audit.recommendations?.length > 0 && (
                                <div className="audit-section recommendations">
                                    <h4>Recommendations</h4>
                                    <ul>
                                        {audit.recommendations.map((rec, idx) => (
                                            <li key={idx}>{rec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default AuditTab;
