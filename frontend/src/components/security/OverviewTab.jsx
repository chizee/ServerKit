import React, { useState, useEffect } from 'react';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

const InstallClamAVButton = ({ onInstalled }) => {
    const [installing, setInstalling] = useState(false);
    const [error, setError] = useState(null);

    async function handleInstall() {
        setInstalling(true);
        setError(null);
        try {
            await api.installClamAV();
            onInstalled();
        } catch (err) {
            setError(err.message);
        } finally {
            setInstalling(false);
        }
    }

    return (
        <div>
            <Button variant="default" onClick={handleInstall} disabled={installing}>
                {installing ? 'Installing...' : 'Install ClamAV'}
            </Button>
            {error && <p className="error-text" style={{ marginTop: '0.5rem' }}>{error}</p>}
        </div>
    );
};

const OverviewTab = ({ status, onRefresh }) => {
    const [clamavStatus, setClamavStatus] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadClamavStatus();
    }, []);

    async function loadClamavStatus() {
        try {
            const data = await api.getClamAVStatus();
            setClamavStatus(data);
        } catch (err) {
            console.error('Failed to load ClamAV status:', err);
        } finally {
            setLoading(false);
        }
    }

    const alerts = status?.recent_alerts || {};

    return (
        <div className="security-overview">
            <div className="stats-grid">
                <div className={`stat-card ${alerts.total > 0 ? 'warning' : 'success'}`}>
                    <div className="stat-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                        </svg>
                    </div>
                    <div className="stat-content">
                        <span className="stat-value">{alerts.total || 0}</span>
                        <span className="stat-label">Alerts (24h)</span>
                    </div>
                </div>

                <div className={`stat-card ${alerts.malware_detections > 0 ? 'danger' : 'success'}`}>
                    <div className="stat-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                        </svg>
                    </div>
                    <div className="stat-content">
                        <span className="stat-value">{alerts.malware_detections || 0}</span>
                        <span className="stat-label">Malware Detected</span>
                    </div>
                </div>

                <div className={`stat-card ${clamavStatus?.installed ? 'success' : 'warning'}`}>
                    <div className="stat-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"/>
                            {clamavStatus?.installed && <polyline points="9 12 12 15 16 10"/>}
                            {!clamavStatus?.installed && <line x1="15" y1="9" x2="9" y2="15"/>}
                        </svg>
                    </div>
                    <div className="stat-content">
                        <span className="stat-value">{clamavStatus?.installed ? 'Active' : 'Not Installed'}</span>
                        <span className="stat-label">ClamAV Status</span>
                    </div>
                </div>

                <div className={`stat-card ${status?.scan_status === 'running' ? 'info' : 'default'}`}>
                    <div className="stat-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" fill="none" strokeWidth="2">
                            <circle cx="11" cy="11" r="8"/>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                    </div>
                    <div className="stat-content">
                        <span className="stat-value" style={{ textTransform: 'capitalize' }}>{status?.scan_status || 'Idle'}</span>
                        <span className="stat-label">Scan Status</span>
                    </div>
                </div>
            </div>

            <div className="security-grid">
                <div className="card">
                    <div className="card-header">
                        <h3>ClamAV Antivirus</h3>
                        <Button variant="outline" size="sm" onClick={loadClamavStatus}>Refresh</Button>
                    </div>
                    <div className="card-body">
                        {loading ? (
                            <div className="loading-sm">Loading...</div>
                        ) : clamavStatus?.installed ? (
                            <div className="info-list">
                                <div className="info-item">
                                    <span className="info-label">Version</span>
                                    <span className="info-value">{clamavStatus.version || 'Unknown'}</span>
                                </div>
                                <div className="info-item">
                                    <span className="info-label">Service</span>
                                    <Badge variant={clamavStatus.service_running ? 'success' : 'warning'}>
                                        {clamavStatus.service_running ? 'Running' : 'Stopped'}
                                    </Badge>
                                </div>
                                <div className="info-item">
                                    <span className="info-label">Last Definition Update</span>
                                    <span className="info-value">
                                        {clamavStatus.last_update ? new Date(clamavStatus.last_update).toLocaleString() : 'Unknown'}
                                    </span>
                                </div>
                            </div>
                        ) : (
                            <div className="not-installed">
                                <p>ClamAV is not installed on this server.</p>
                                <InstallClamAVButton onInstalled={loadClamavStatus} />
                            </div>
                        )}
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">
                        <h3>File Integrity Monitoring</h3>
                    </div>
                    <div className="card-body">
                        <div className="info-list">
                            <div className="info-item">
                                <span className="info-label">Status</span>
                                <Badge variant={status?.file_integrity?.enabled ? 'success' : 'secondary'}>
                                    {status?.file_integrity?.enabled ? 'Enabled' : 'Disabled'}
                                </Badge>
                            </div>
                            <div className="info-item">
                                <span className="info-label">Database</span>
                                <Badge variant={status?.file_integrity?.database_exists ? 'success' : 'warning'}>
                                    {status?.file_integrity?.database_exists ? 'Initialized' : 'Not Initialized'}
                                </Badge>
                            </div>
                            <div className="info-item">
                                <span className="info-label">Changes Detected (24h)</span>
                                <span className="info-value">{alerts.integrity_changes || 0}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">
                        <h3>Notifications</h3>
                    </div>
                    <div className="card-body">
                        <div className="info-list">
                            <div className="info-item">
                                <span className="info-label">Security Alerts</span>
                                <Badge variant={status?.notifications_enabled ? 'success' : 'secondary'}>
                                    {status?.notifications_enabled ? 'Enabled' : 'Disabled'}
                                </Badge>
                            </div>
                        </div>
                        <p className="help-text" style={{ marginTop: '1rem' }}>
                            Configure notification channels in Settings → Notifications to receive security alerts via Discord, Slack, or Telegram.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default OverviewTab;
