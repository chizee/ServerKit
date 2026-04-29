import React, { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../services/api';
import { Button } from '@/components/ui/button';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';

function formatBytes(bytes) {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

function formatUptime(seconds) {
    if (!seconds) return '-';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    const parts = [];
    if (days > 0) parts.push(`${days}d`);
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);

    return parts.join(' ') || '< 1m';
}

const SystemTab = () => {
    const { isAdmin } = useAuth();
    const [metrics, setMetrics] = useState(null);
    const [loading, setLoading] = useState(true);
    const [timezones, setTimezones] = useState([]);
    const [selectedTimezone, setSelectedTimezone] = useState('');
    const [savingTimezone, setSavingTimezone] = useState(false);
    const [timezoneMessage, setTimezoneMessage] = useState(null);

    useEffect(() => {
        if (isAdmin) {
            loadMetrics();
            loadTimezones();
        }
    }, [isAdmin]);

    async function loadMetrics() {
        try {
            const data = await api.getSystemMetrics();
            setMetrics(data);
            if (data?.time?.timezone_id) {
                setSelectedTimezone(data.time.timezone_id);
            }
        } catch (err) {
            console.error('Failed to load metrics:', err);
        } finally {
            setLoading(false);
        }
    }

    async function loadTimezones() {
        try {
            const data = await api.getTimezones();
            setTimezones(data.timezones || []);
        } catch (err) {
            console.error('Failed to load timezones:', err);
        }
    }

    async function handleTimezoneChange() {
        if (!selectedTimezone) return;

        setSavingTimezone(true);
        setTimezoneMessage(null);

        try {
            const result = await api.setTimezone(selectedTimezone);
            setTimezoneMessage({ type: 'success', text: result.message || 'Timezone updated' });
            // Refresh metrics to show new time
            loadMetrics();
        } catch (err) {
            setTimezoneMessage({ type: 'error', text: err.message || 'Failed to set timezone' });
        } finally {
            setSavingTimezone(false);
            setTimeout(() => setTimezoneMessage(null), 5000);
        }
    }

    if (!isAdmin) {
        return (
            <div className="settings-section">
                <div className="section-header">
                    <h2>System Information</h2>
                    <p>View system details and server information</p>
                </div>
                <div className="alert alert-warning">
                    Admin access required to view system information.
                </div>
            </div>
        );
    }

    if (loading) {
        return <div className="loading">Loading system information...</div>;
    }

    return (
        <div className="settings-section">
            <div className="section-header">
                <h2>System Information</h2>
                <p>View system details and server information</p>
            </div>

            <div className="system-info-grid">
                <div className="settings-card">
                    <h3>CPU</h3>
                    <div className="info-list">
                        <div className="info-item">
                            <span className="info-label">Usage</span>
                            <span className="info-value">{metrics?.cpu?.percent?.toFixed(1) || 0}%</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Cores</span>
                            <span className="info-value">{metrics?.cpu?.count || '-'}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Load Average</span>
                            <span className="info-value">
                                {metrics?.cpu?.load_avg ? metrics.cpu.load_avg.map(l => l.toFixed(2)).join(', ') : '-'}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="settings-card">
                    <h3>Memory</h3>
                    <div className="info-list">
                        <div className="info-item">
                            <span className="info-label">Usage</span>
                            <span className="info-value">{metrics?.memory?.percent?.toFixed(1) || 0}%</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Used</span>
                            <span className="info-value">{formatBytes(metrics?.memory?.used)}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Total</span>
                            <span className="info-value">{formatBytes(metrics?.memory?.total)}</span>
                        </div>
                    </div>
                </div>

                <div className="settings-card">
                    <h3>Disk</h3>
                    <div className="info-list">
                        <div className="info-item">
                            <span className="info-label">Usage</span>
                            <span className="info-value">{metrics?.disk?.percent?.toFixed(1) || 0}%</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Used</span>
                            <span className="info-value">{formatBytes(metrics?.disk?.used)}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Total</span>
                            <span className="info-value">{formatBytes(metrics?.disk?.total)}</span>
                        </div>
                    </div>
                </div>

                <div className="settings-card">
                    <h3>Network</h3>
                    <div className="info-list">
                        <div className="info-item">
                            <span className="info-label">Bytes Sent</span>
                            <span className="info-value">{formatBytes(metrics?.network?.bytes_sent)}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Bytes Received</span>
                            <span className="info-value">{formatBytes(metrics?.network?.bytes_recv)}</span>
                        </div>
                    </div>
                </div>
            </div>

            {metrics?.system && (
                <div className="settings-card">
                    <h3>System Details</h3>
                    <div className="info-list">
                        <div className="info-item">
                            <span className="info-label">Hostname</span>
                            <span className="info-value">{metrics.system.hostname || '-'}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Platform</span>
                            <span className="info-value">{metrics.system.platform || '-'}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">OS Version</span>
                            <span className="info-value">{metrics.system.version || '-'}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Uptime</span>
                            <span className="info-value">{formatUptime(metrics.system.uptime)}</span>
                        </div>
                    </div>
                </div>
            )}

            {/* Server Time & Timezone */}
            <div className="settings-card">
                <h3>Server Time & Timezone</h3>
                {metrics?.time && (
                    <div className="info-list" style={{ marginBottom: '1rem' }}>
                        <div className="info-item">
                            <span className="info-label">Current Time</span>
                            <span className="info-value">{metrics.time.current_time_formatted}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">UTC Offset</span>
                            <span className="info-value">{metrics.time.utc_offset}</span>
                        </div>
                        <div className="info-item">
                            <span className="info-label">Current Timezone</span>
                            <span className="info-value">{metrics.time.timezone_id || metrics.time.timezone_name}</span>
                        </div>
                    </div>
                )}
                <div className="form-group">
                    <label>Change Timezone</label>
                    <div className="timezone-selector">
                        <Select
                            value={selectedTimezone || '__none__'}
                            onValueChange={(val) => setSelectedTimezone(val === '__none__' ? '' : val)}
                        >
                            <SelectTrigger>
                                <SelectValue placeholder="Select timezone..." />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="__none__">Select timezone...</SelectItem>
                                {timezones.map((tz) => (
                                    <SelectItem key={tz} value={tz}>{tz}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Button
                            variant="default"
                            onClick={handleTimezoneChange}
                            disabled={savingTimezone || !selectedTimezone || selectedTimezone === metrics?.time?.timezone_id}
                        >
                            {savingTimezone ? 'Saving...' : 'Apply'}
                        </Button>
                    </div>
                    {timezoneMessage && (
                        <div className={`timezone-message ${timezoneMessage.type}`}>
                            {timezoneMessage.text}
                        </div>
                    )}
                    <span className="form-help">
                        Changing timezone requires server restart to take full effect
                    </span>
                </div>
            </div>
        </div>
    );
};

export default SystemTab;
