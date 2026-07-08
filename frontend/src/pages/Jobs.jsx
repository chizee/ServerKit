// Jobs — admin view over the unified job system (job orchestration, "Phase 9").
//
// NOTE: This file was reconstructed after a data-loss corruption. It is wired to
// the real ApiService job methods (see frontend/src/services/api/jobs.js) and
// follows the host page idioms (PageTopbar + DS components), but the exact
// original layout could not be recovered — this is a faithful, functional
// rebuild rather than a byte-for-byte restore.
import { useState, useEffect, useCallback, useRef } from 'react';
import { ListChecks, RefreshCw, RotateCcw, XCircle, Play, Clock } from 'lucide-react';
import api from '../services/api';
import { PageTopbar, MetricCard, KpiBand, Pill } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { timeAgo } from '../utils/timeAgo';

const STATUSES = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'];
const POLL_MS = 5000;

// Map a job status to a DS Pill colour.
const STATUS_KIND = {
    queued: 'gray',
    scheduled: 'gray',
    running: 'cyan',
    succeeded: 'green',
    success: 'green',
    completed: 'green',
    failed: 'red',
    error: 'red',
    cancelled: 'amber',
    canceled: 'amber',
};

function statusKind(status) {
    return STATUS_KIND[String(status || '').toLowerCase()] || 'gray';
}

export default function Jobs() {
    const { isAdmin } = useAuth();
    const toast = useToast();
    const [jobs, setJobs] = useState([]);
    const [stats, setStats] = useState(null);
    const [scheduled, setScheduled] = useState([]);
    const [status, setStatus] = useState('all');
    const [kind, setKind] = useState('all');
    const [kinds, setKinds] = useState([]);
    const [loading, setLoading] = useState(true);
    const pollRef = useRef(null);

    const load = useCallback(async () => {
        try {
            const params = { limit: 100 };
            if (status !== 'all') params.status = status;
            if (kind !== 'all') params.kind = kind;
            const [jobsRes, statsRes, schedRes] = await Promise.all([
                api.getJobs(params),
                api.getJobStats().catch(() => null),
                api.getScheduledJobs().catch(() => null),
            ]);
            setJobs(jobsRes?.jobs || jobsRes || []);
            setStats(statsRes?.stats || statsRes || null);
            setScheduled(schedRes?.scheduled || schedRes?.jobs || schedRes || []);
        } catch {
            // Keep the last good state on screen rather than blanking the page.
        } finally {
            setLoading(false);
        }
    }, [status, kind]);

    useEffect(() => {
        if (!isAdmin) return undefined;
        api.getJobKinds()
            .then((res) => setKinds(res?.kinds || res || []))
            .catch(() => { /* filter just won't populate */ });
        return undefined;
    }, [isAdmin]);

    useEffect(() => {
        if (!isAdmin) return undefined;
        load();
        pollRef.current = setInterval(load, POLL_MS);
        return () => clearInterval(pollRef.current);
    }, [isAdmin, load]);

    const onRetry = async (id) => {
        try {
            await api.retryJob(id);
            toast.success('Job re-queued');
            load();
        } catch {
            toast.error('Retry failed');
        }
    };

    const onCancel = async (id) => {
        try {
            await api.cancelJob(id);
            toast.success('Job cancelled');
            load();
        } catch {
            toast.error('Cancel failed');
        }
    };

    const onRunScheduled = async (id) => {
        try {
            await api.runScheduledJob(id);
            toast.success('Scheduled job triggered');
            load();
        } catch {
            toast.error('Trigger failed');
        }
    };

    const onToggleScheduled = async (id, enabled) => {
        try {
            await api.setScheduledJobEnabled(id, enabled);
            load();
        } catch {
            toast.error('Update failed');
        }
    };

    if (!isAdmin) {
        return (
            <>
                <PageTopbar icon={<ListChecks size={18} />} title="Jobs" />
                <div className="sk-jobs"><div className="sk-jobs__empty">Admins only.</div></div>
            </>
        );
    }

    const byStatus = stats?.by_status || {};
    const isRunning = (s) => ['running', 'queued', 'scheduled'].includes(String(s || '').toLowerCase());
    const canRetry = (s) => ['failed', 'error', 'cancelled', 'canceled'].includes(String(s || '').toLowerCase());

    return (
        <>
            <PageTopbar
                icon={<ListChecks size={18} />}
                title="Jobs"
                meta="Unified job orchestration across the panel"
                actions={(
                    <Button variant="outline" size="sm" onClick={load}>
                        <RefreshCw size={14} /> Refresh
                    </Button>
                )}
            />

            <div className="sk-jobs">
                <KpiBand>
                    <MetricCard label="Total" value={stats?.total ?? jobs.length ?? 0} tone="accent" />
                    <MetricCard label="Running" value={byStatus.running ?? 0} tone="cyan" />
                    <MetricCard label="Queued" value={byStatus.queued ?? 0} tone="amber" />
                    <MetricCard label="Failed" value={byStatus.failed ?? 0} tone="red" />
                </KpiBand>

                <div className="sk-jobs__filters">
                    <label>
                        Status
                        <select value={status} onChange={(e) => setStatus(e.target.value)}>
                            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </label>
                    <label>
                        Kind
                        <select value={kind} onChange={(e) => setKind(e.target.value)}>
                            <option value="all">all</option>
                            {kinds.map((k) => {
                                const value = typeof k === 'string' ? k : k.kind || k.name;
                                return <option key={value} value={value}>{value}</option>;
                            })}
                        </select>
                    </label>
                </div>

                {loading && jobs.length === 0 ? (
                    <div className="sk-jobs__empty">Loading…</div>
                ) : jobs.length === 0 ? (
                    <div className="sk-jobs__empty">
                        <ListChecks size={24} aria-hidden="true" />
                        <p>No jobs match these filters.</p>
                    </div>
                ) : (
                    <div className="sk-jobs__table-wrap">
                        <table className="sk-jobs__table">
                            <thead>
                                <tr>
                                    <th>Status</th>
                                    <th>Kind</th>
                                    <th>Owner</th>
                                    <th>Progress</th>
                                    <th>When</th>
                                    <th aria-label="Actions" />
                                </tr>
                            </thead>
                            <tbody>
                                {jobs.map((job) => (
                                    <tr key={job.id}>
                                        <td>
                                            <Pill kind={statusKind(job.status)}>{job.status}</Pill>
                                        </td>
                                        <td className="sk-jobs__kind">{job.kind || '—'}</td>
                                        <td className="sk-jobs__owner">
                                            {job.owner_type
                                                ? `${job.owner_type}${job.owner_id ? ` #${job.owner_id}` : ''}`
                                                : '—'}
                                        </td>
                                        <td>
                                            {typeof job.progress === 'number'
                                                ? `${Math.round(job.progress)}%`
                                                : (job.completed_units != null && job.total_units != null)
                                                    ? `${job.completed_units}/${job.total_units}`
                                                    : '—'}
                                            {job.error && (
                                                <div className="sk-jobs__error" title={job.error}>{job.error}</div>
                                            )}
                                        </td>
                                        <td className="sk-jobs__when">
                                            {timeAgo(job.created_at || job.updated_at)}
                                        </td>
                                        <td className="sk-jobs__actions">
                                            {isRunning(job.status) && (
                                                <Button variant="ghost" size="sm" onClick={() => onCancel(job.id)}>
                                                    <XCircle size={14} /> Cancel
                                                </Button>
                                            )}
                                            {canRetry(job.status) && (
                                                <Button variant="ghost" size="sm" onClick={() => onRetry(job.id)}>
                                                    <RotateCcw size={14} /> Retry
                                                </Button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {scheduled.length > 0 && (
                    <section className="sk-jobs__scheduled">
                        <h2 className="sk-jobs__section-title">
                            <Clock size={16} aria-hidden="true" /> Scheduled jobs
                        </h2>
                        <div className="sk-jobs__table-wrap">
                            <table className="sk-jobs__table">
                                <thead>
                                    <tr>
                                        <th>Name</th>
                                        <th>Kind</th>
                                        <th>Schedule</th>
                                        <th>Next run</th>
                                        <th>Enabled</th>
                                        <th aria-label="Actions" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {scheduled.map((sched) => (
                                        <tr key={sched.id}>
                                            <td>{sched.name || sched.kind || `#${sched.id}`}</td>
                                            <td className="sk-jobs__kind">{sched.kind || '—'}</td>
                                            <td className="sk-jobs__owner">{sched.schedule || sched.cron || '—'}</td>
                                            <td className="sk-jobs__when">
                                                {sched.next_run_at ? timeAgo(sched.next_run_at) : '—'}
                                            </td>
                                            <td>
                                                <Pill kind={sched.enabled ? 'green' : 'gray'}>
                                                    {sched.enabled ? 'On' : 'Off'}
                                                </Pill>
                                            </td>
                                            <td className="sk-jobs__actions">
                                                <Button variant="ghost" size="sm" onClick={() => onRunScheduled(sched.id)}>
                                                    <Play size={14} /> Run now
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => onToggleScheduled(sched.id, !sched.enabled)}
                                                >
                                                    {sched.enabled ? 'Disable' : 'Enable'}
                                                </Button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}
            </div>
        </>
    );
}
