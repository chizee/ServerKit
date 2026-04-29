import React, { useState, useEffect } from 'react';
import api from '../../services/api';
import { Database, Loader, CheckCircle, ArrowUpCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

const MigrationHistoryTab = () => {
    const [revisions, setRevisions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        loadHistory();
    }, []);

    async function loadHistory() {
        try {
            setLoading(true);
            const data = await api.getMigrationHistory();
            setRevisions(data.revisions || []);
        } catch (err) {
            setError(err.message || 'Failed to load migration history');
        } finally {
            setLoading(false);
        }
    }

    if (loading) {
        return (
            <div className="settings-section">
                <div className="loading-state">
                    <Loader size={20} className="spin" />
                    <span>Loading migration history...</span>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="settings-section">
                <div className="empty-state">
                    <p>{error}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="settings-section">
            <div className="settings-section-header">
                <h2>Database Migrations</h2>
                <p className="settings-section-description">
                    History of all database schema versions applied to this instance.
                </p>
            </div>

            {revisions.length === 0 ? (
                <div className="empty-state">
                    <Database size={32} />
                    <p>No migration history found.</p>
                </div>
            ) : (
                <div className="table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Revision</th>
                                <th>Description</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {revisions.map((rev, i) => (
                                <tr key={i}>
                                    <td>
                                        <code>{rev.revision.substring(0, 16)}</code>
                                    </td>
                                    <td>{rev.description || 'Schema update'}</td>
                                    <td>
                                        {rev.is_current && (
                                            <Badge variant="success">
                                                <CheckCircle size={12} /> Current
                                            </Badge>
                                        )}
                                        {rev.is_head && !rev.is_current && (
                                            <Badge variant="warning">
                                                <ArrowUpCircle size={12} /> Pending
                                            </Badge>
                                        )}
                                        {!rev.is_current && !rev.is_head && (
                                            <Badge variant="secondary">Applied</Badge>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default MigrationHistoryTab;
