import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
    Activity,
    CheckCircle2,
    XCircle,
    Clock,
    RefreshCw,
    Server,
    Loader2,
    AlertTriangle,
    PlayCircle,
} from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { Button } from '@/components/ui/button';

const STATUS_COLORS = {
    pending: { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8', icon: Clock },
    running: { bg: 'rgba(99,102,241,0.15)', fg: '#6366f1', icon: Loader2 },
    succeeded: { bg: 'rgba(34,197,94,0.15)', fg: '#22c55e', icon: CheckCircle2 },
    failed: { bg: 'rgba(239,68,68,0.15)', fg: '#ef4444', icon: XCircle },
};

const formatDuration = (seconds) => {
    if (seconds == null) return '—';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
};

const formatTime = (iso) => {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
};

const StatusBadge = ({ status }) => {
    const cfg = STATUS_COLORS[status] || STATUS_COLORS.pending;
    const Icon = cfg.icon;
    const spin = status === 'running';
    return (
        <span
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 10px',
                borderRadius: 999,
                background: cfg.bg,
                color: cfg.fg,
                fontSize: 12,
                fontWeight: 600,
                textTransform: 'capitalize',
            }}
        >
            <Icon size={14} className={spin ? 'spin' : ''} />
            {status}
        </span>
    );
};

const Deployments = () => {
    const toast = useToast();
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('all');
    const [serverFilter, setServerFilter] = useState('all');
    const [servers, setServers] = useState([]);
    const [selectedJob, setSelectedJob] = useState(null);
    const [jobDetail, setJobDetail] = useState(null);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const refreshRef = useRef(null);
    const detailRef = useRef(null);

    const loadJobs = async () => {
        try {
            const params = {};
            if (statusFilter !== 'all') params.status = statusFilter;
            if (serverFilter !== 'all') params.serverId = serverFilter;
            const data = await api.getDeploymentJobs(params);
            setJobs(data.jobs || []);
        } catch (err) {
            console.error('Failed to load deployment jobs', err);
        } finally {
            setLoading(false);
        }
    };

    const loadServers = async () => {
        try {
            const data = await api.getAvailableServers();
            setServers(Array.isArray(data) ? data : []);
        } catch {
            setServers([]);
        }
    };

    const loadJobDetail = async (jobId) => {
        if (!jobId) return;
        try {
            const data = await api.getDeploymentJob(jobId, true);
            setJobDetail(data.job || null);
        } catch (err) {
            console.error('Failed to load deployment job detail', err);
        }
    };

    useEffect(() => {
        loadServers();
    }, []);

    useEffect(() => {
        loadJobs();
    }, [statusFilter, serverFilter]);

    useEffect(() => {
        if (refreshRef.current) clearInterval(refreshRef.current);
        if (!autoRefresh) return undefined;
        refreshRef.current = setInterval(() => {
            loadJobs();
            if (selectedJob) loadJobDetail(selectedJob);
        }, 3000);
        return () => clearInterval(refreshRef.current);
    }, [autoRefresh, selectedJob, statusFilter, serverFilter]);

    useEffect(() => {
        if (selectedJob) loadJobDetail(selectedJob);
        else setJobDetail(null);
    }, [selectedJob]);

    useEffect(() => {
        if (detailRef.current) {
            detailRef.current.scrollTop = detailRef.current.scrollHeight;
        }
    }, [jobDetail?.logs?.length]);

    const summary = useMemo(() => {
        const counts = { running: 0, succeeded: 0, failed: 0, pending: 0 };
        jobs.forEach((j) => {
            counts[j.status] = (counts[j.status] || 0) + 1;
        });
        return counts;
    }, [jobs]);

    return (
        <div className="page-container">
            <div className="page-header">
                <div>
                    <h1 className="page-title">
                        <Activity size={24} style={{ marginRight: 8, verticalAlign: 'middle' }} />
                        Deployments
                    </h1>
                    <p className="page-description">
                        Track deployment jobs across all servers — see real-time status, step-by-step progress, and logs.
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    <Button
                        variant={autoRefresh ? 'default' : 'outline'}
                        onClick={() => setAutoRefresh((v) => !v)}
                        title="Auto-refresh every 3s"
                    >
                        <RefreshCw size={16} className={autoRefresh ? 'spin' : ''} />
                        {autoRefresh ? 'Live' : 'Paused'}
                    </Button>
                    <Button variant="outline" onClick={loadJobs}>
                        <RefreshCw size={16} /> Refresh
                    </Button>
                </div>
            </div>

            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: 12,
                    marginBottom: 16,
                }}
            >
                {[
                    { label: 'Running', value: summary.running, icon: Loader2, color: '#6366f1' },
                    { label: 'Succeeded', value: summary.succeeded, icon: CheckCircle2, color: '#22c55e' },
                    { label: 'Failed', value: summary.failed, icon: XCircle, color: '#ef4444' },
                    { label: 'Pending', value: summary.pending, icon: Clock, color: '#94a3b8' },
                ].map((s) => {
                    const Icon = s.icon;
                    return (
                        <div key={s.label} className="card" style={{ padding: 16 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <Icon size={20} style={{ color: s.color }} />
                                <div>
                                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{s.label}</div>
                                    <div style={{ fontSize: 22, fontWeight: 700 }}>{s.value}</div>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <div>
                    <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block' }}>Status</label>
                    <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                        <option value="all">All</option>
                        <option value="pending">Pending</option>
                        <option value="running">Running</option>
                        <option value="succeeded">Succeeded</option>
                        <option value="failed">Failed</option>
                    </select>
                </div>
                <div>
                    <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block' }}>Target server</label>
                    <select value={serverFilter} onChange={(e) => setServerFilter(e.target.value)}>
                        <option value="all">All servers</option>
                        {servers.map((s) => (
                            <option key={s.id} value={s.id}>
                                {s.name}{s.is_local ? ' (local)' : ''}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr)', gap: 16 }}>
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    {loading ? (
                        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-secondary)' }}>Loading…</div>
                    ) : jobs.length === 0 ? (
                        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-secondary)' }}>
                            <PlayCircle size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
                            <div>No deployment jobs yet.</div>
                            <div style={{ fontSize: 13, marginTop: 4 }}>
                                Install a template or trigger a deploy to see it here.
                            </div>
                        </div>
                    ) : (
                        <table className="data-table" style={{ width: '100%' }}>
                            <thead>
                                <tr>
                                    <th>Status</th>
                                    <th>Kind</th>
                                    <th>Target</th>
                                    <th>App</th>
                                    <th>Progress</th>
                                    <th>Started</th>
                                </tr>
                            </thead>
                            <tbody>
                                {jobs.map((job) => (
                                    <tr
                                        key={job.id}
                                        onClick={() => setSelectedJob(job.id)}
                                        style={{
                                            cursor: 'pointer',
                                            background: selectedJob === job.id ? 'var(--accent-glow)' : 'transparent',
                                        }}
                                    >
                                        <td><StatusBadge status={job.status} /></td>
                                        <td>{job.kind}</td>
                                        <td>
                                            <Server size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                                            {job.target_server_name || 'Local server'}
                                        </td>
                                        <td>{job.app_name || '—'}</td>
                                        <td>
                                            <div
                                                style={{
                                                    height: 6,
                                                    background: 'var(--bg-elevated)',
                                                    borderRadius: 3,
                                                    overflow: 'hidden',
                                                    minWidth: 80,
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        width: `${job.progress_percent || 0}%`,
                                                        height: '100%',
                                                        background:
                                                            job.status === 'failed' ? '#ef4444' : 'var(--accent-primary)',
                                                        transition: 'width 200ms ease',
                                                    }}
                                                />
                                            </div>
                                            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                                                {job.current_step || 0}/{job.total_steps || 0}
                                            </div>
                                        </td>
                                        <td style={{ fontSize: 12 }}>{formatTime(job.started_at || job.created_at)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>

                <div className="card" style={{ padding: 16, minHeight: 400 }}>
                    {!selectedJob ? (
                        <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 48 }}>
                            Select a job to view its plan and logs.
                        </div>
                    ) : !jobDetail ? (
                        <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 48 }}>Loading…</div>
                    ) : (
                        <>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                                <div>
                                    <h3 style={{ margin: 0 }}>{jobDetail.app_name || jobDetail.kind}</h3>
                                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                                        {jobDetail.id}
                                    </div>
                                </div>
                                <StatusBadge status={jobDetail.status} />
                            </div>

                            <div
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                                    gap: 12,
                                    marginTop: 16,
                                    fontSize: 13,
                                }}
                            >
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Target</div>
                                    <div>{jobDetail.target_server_name}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Step</div>
                                    <div>{jobDetail.current_step || 0} / {jobDetail.total_steps || 0}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Duration</div>
                                    <div>{formatDuration(jobDetail.duration)}</div>
                                </div>
                                <div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Started</div>
                                    <div>{formatTime(jobDetail.started_at)}</div>
                                </div>
                            </div>

                            {jobDetail.current_step_name && jobDetail.status === 'running' && (
                                <div
                                    style={{
                                        marginTop: 12,
                                        padding: 10,
                                        background: 'rgba(99,102,241,0.1)',
                                        borderRadius: 6,
                                        fontSize: 13,
                                    }}
                                >
                                    <Loader2 size={14} className="spin" style={{ marginRight: 6, verticalAlign: 'middle' }} />
                                    {jobDetail.current_step_name}
                                </div>
                            )}

                            {jobDetail.error_message && (
                                <div
                                    style={{
                                        marginTop: 12,
                                        padding: 10,
                                        background: 'rgba(239,68,68,0.1)',
                                        border: '1px solid rgba(239,68,68,0.3)',
                                        borderRadius: 6,
                                        color: '#ef4444',
                                        fontSize: 13,
                                    }}
                                >
                                    <AlertTriangle size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                                    {jobDetail.error_message}
                                </div>
                            )}

                            <h4 style={{ marginTop: 20, marginBottom: 8 }}>Logs</h4>
                            <div
                                ref={detailRef}
                                style={{
                                    background: '#0b0f1a',
                                    color: '#cbd5e1',
                                    padding: 12,
                                    borderRadius: 6,
                                    fontFamily: 'ui-monospace, SFMono-Regular, monospace',
                                    fontSize: 12,
                                    height: 360,
                                    overflowY: 'auto',
                                    whiteSpace: 'pre-wrap',
                                }}
                            >
                                {(jobDetail.logs || []).length === 0
                                    ? 'Waiting for logs…'
                                    : jobDetail.logs.map((log) => {
                                        const ts = log.created_at ? new Date(log.created_at).toLocaleTimeString() : '';
                                        const stepPrefix = log.step_index ? `[${log.step_index}] ` : '';
                                        const color =
                                            log.level === 'error'
                                                ? '#fca5a5'
                                                : log.level === 'debug'
                                                ? '#94a3b8'
                                                : '#cbd5e1';
                                        return (
                                            <div key={log.id} style={{ color }}>
                                                <span style={{ color: '#64748b' }}>{ts}</span>{' '}
                                                <span style={{ color: '#94a3b8' }}>{log.level.toUpperCase()}</span>{' '}
                                                {stepPrefix}{log.message}
                                            </div>
                                        );
                                    })}
                            </div>
                        </>
                    )}
                </div>
            </div>

            <style>{`
                .spin { animation: spin 1s linear infinite; }
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            `}</style>
        </div>
    );
};

export default Deployments;
