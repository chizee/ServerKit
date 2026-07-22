import { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
    CheckCircle2,
    XCircle,
    Clock,
    RefreshCw,
    Server,
    Loader2,
    GitBranch,
    PlayCircle,
} from 'lucide-react';
import api from '../services/api';
import { StatStrip, Stat } from '../components/StatCard';
import { Button } from '@/components/ui/button';
import { useTopbarActions } from '@/hooks/useTopbarActions';

const STATUS_COLORS = {
    pending: { bg: 'var(--surface-3)', fg: 'var(--text-faint)', icon: Clock },
    running: { bg: 'var(--accent-bg)', fg: 'var(--accent-bright)', icon: Loader2 },
    succeeded: { bg: 'var(--green-bg)', fg: 'var(--green)', icon: CheckCircle2 },
    failed: { bg: 'var(--red-bg)', fg: 'var(--red)', icon: XCircle },
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
        <span className="deployments-page__status-badge" style={{ background: cfg.bg, color: cfg.fg }}>
            <Icon size={14} className={spin ? 'deployments-page__spin' : ''} />
            {status}
        </span>
    );
};

const Deployments = () => {
    const navigate = useNavigate();
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('all');
    const [serverFilter, setServerFilter] = useState('all');
    const [servers, setServers] = useState([]);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const refreshRef = useRef(null);

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

    useEffect(() => {
        loadServers();
    }, []);

    useEffect(() => {
        loadJobs();
    }, [statusFilter, serverFilter]);

    useEffect(() => {
        if (refreshRef.current) clearInterval(refreshRef.current);
        if (!autoRefresh) return undefined;
        refreshRef.current = setInterval(loadJobs, 3000);
        return () => clearInterval(refreshRef.current);
    }, [autoRefresh, statusFilter, serverFilter]);

    const summary = useMemo(() => {
        const counts = { running: 0, succeeded: 0, failed: 0, pending: 0 };
        jobs.forEach((j) => {
            counts[j.status] = (counts[j.status] || 0) + 1;
        });
        return counts;
    }, [jobs]);

    useTopbarActions(() =>
        <>
            <Button variant="outline" size="sm" asChild>
                <Link to="/services/new">
                    <GitBranch size={16} />
                    New Service
                </Link>
            </Button>
            <Button
                variant={autoRefresh ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAutoRefresh((v) => !v)}
                title="Auto-refresh every 3s"
            >
                <RefreshCw size={16} className={autoRefresh ? 'spin' : ''} />
                {autoRefresh ? 'Live' : 'Paused'}
            </Button>
            <Button variant="outline" size="sm" onClick={loadJobs}>
                <RefreshCw size={16} /> Refresh
            </Button>
        </>,
        [autoRefresh]
    );

    return (
        <div className="sk-tabgroup__inner deployments-page">
            <StatStrip ariaLabel="Deployment summary">
                <Stat label="Running" value={summary.running} state={summary.running > 0 ? 'info' : undefined} />
                <Stat label="Succeeded" value={summary.succeeded} state={summary.succeeded > 0 ? 'success' : undefined} />
                <Stat label="Failed" value={summary.failed} state={summary.failed > 0 ? 'danger' : undefined} />
                <Stat label="Pending" value={summary.pending} />
            </StatStrip>

            <div className="deployments-page__toolbar">
                <div className="deployments-page__filter">
                    <label>Status</label>
                    <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                        <option value="all">All</option>
                        <option value="pending">Pending</option>
                        <option value="running">Running</option>
                        <option value="succeeded">Succeeded</option>
                        <option value="failed">Failed</option>
                    </select>
                </div>
                <div className="deployments-page__filter">
                    <label>Target server</label>
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

            <div className="deployments-page__workspace">
                <div className="deployments-page__panel deployments-page__jobs-panel">
                    <div className="deployments-page__panel-header">
                        <div>
                            <h2>Jobs</h2>
                            <span>{jobs.length} visible</span>
                        </div>
                    </div>
                    {loading ? (
                        <div className="deployments-page__empty">Loading...</div>
                    ) : jobs.length === 0 ? (
                        <div className="deployments-page__empty">
                            <PlayCircle size={34} />
                            <strong>No deployment jobs yet</strong>
                            <span>
                                Create a service from a repository or install a template to see activity here.
                            </span>
                        </div>
                    ) : (
                        <table className="deployments-page__jobs-table">
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
                                        onClick={() => navigate(`/deployments/${job.id}`)}
                                        title="Open the Deploy Console"
                                    >
                                        <td><StatusBadge status={job.status} /></td>
                                        <td>{job.kind}</td>
                                        <td>
                                            <span className="deployments-page__server-cell">
                                                <Server size={12} />
                                                {job.target_server_name || 'Local server'}
                                            </span>
                                        </td>
                                        <td>{job.app_name || '—'}</td>
                                        <td>
                                            <div className="deployments-page__progress">
                                                <div
                                                    style={{
                                                        width: `${job.progress_percent || 0}%`,
                                                        background:
                                                            job.status === 'failed' ? 'var(--red)' : 'var(--accent-primary)',
                                                    }}
                                                />
                                            </div>
                                            <div className="deployments-page__progress-meta">
                                                {job.current_step || 0}/{job.total_steps || 0}
                                            </div>
                                        </td>
                                        <td className="deployments-page__time-cell">{formatTime(job.started_at || job.created_at)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </div>
    );
};

export default Deployments;
