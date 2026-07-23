import { useState, useEffect, useRef, useCallback } from 'react';
import socketService from '../services/socket';
import api from '../services/api';

// Terminal statuses freeze the stream (unsubscribe + stop polling).
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
// Mirror the backend's per-job row cap (plan 51 D4): keep the tail bounded so a
// very chatty build can't grow the DOM unboundedly.
const MAX_LINES = 5000;
// Fall back to polling if the socket hasn't connected shortly after mount.
const SOCKET_GRACE_MS = 2500;

/**
 * Single transport hook for the Deploy Console, the compact progress widget,
 * the LogsTab banner, and the topbar pill (plan 51 §5.5).
 *
 * Boot fetches a full snapshot (GET /deployment-jobs/<id>?logs=true), then
 * prefers the live `deploy_log`/`deploy_status` socket channel and falls back to
 * `after_id` polling when sockets are unavailable. Log rows are de-duplicated by
 * DB id; after any (re)connect the hook re-syncs with `after_id=<max seen id>`
 * so lines emitted while disconnected are never lost.
 *
 * @param {string} jobId
 * @param {object} [opts]
 * @param {number} [opts.pollInterval=2000]
 * @param {boolean} [opts.enabled=true]
 * @returns {{job, lines, isLive, transport, error, loading, refetch}}
 */
export default function useDeployJobStream(jobId, opts = {}) {
    const { pollInterval = 2000, enabled = true, includePlan = false } = opts;

    const [job, setJob] = useState(null);
    const [lines, setLines] = useState([]);
    const [transport, setTransport] = useState('poll');
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(true);

    const maxIdRef = useRef(0);
    const seenRef = useRef(new Set());
    const stoppedRef = useRef(false);
    const pollRef = useRef(null);

    // Merge a batch of log rows, de-duping by id and tracking the high-water id.
    const mergeLines = useCallback((incoming) => {
        if (!incoming || incoming.length === 0) return;
        const fresh = [];
        for (const ln of incoming) {
            if (ln.id != null) {
                if (seenRef.current.has(ln.id)) continue;
                seenRef.current.add(ln.id);
                if (ln.id > maxIdRef.current) maxIdRef.current = ln.id;
            }
            fresh.push(ln);
        }
        if (fresh.length === 0) return;
        setLines((prev) => {
            const next = prev.concat(fresh);
            return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
        });
    }, []);

    const applyJob = useCallback((next) => {
        if (!next) return;
        // The plan is fetched once on boot and never changes; socket status
        // updates don't carry it, so preserve it across replacements.
        setJob((prev) => (prev?.plan && !next.plan ? { ...next, plan: prev.plan } : next));
        if (TERMINAL.has(next.status)) {
            stoppedRef.current = true;
        }
    }, []);

    const stopPolling = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    // after_id poll: pull new log rows + the current job status.
    const pollOnce = useCallback(async () => {
        if (stoppedRef.current || !jobId) return;
        try {
            const [logsRes, jobRes] = await Promise.all([
                api.getDeploymentJobLogs(jobId, maxIdRef.current || null),
                api.getDeploymentJob(jobId, false),
            ]);
            setError(null);
            mergeLines(logsRes?.logs || []);
            applyJob(jobRes?.job);
            if (jobRes?.job && TERMINAL.has(jobRes.job.status)) {
                stopPolling();
            }
        } catch (err) {
            setError(err?.data?.error || err?.message || 'Failed to reach the deployment');
        }
    }, [jobId, mergeLines, applyJob, stopPolling]);

    const startPolling = useCallback(() => {
        if (pollRef.current || stoppedRef.current || pollInterval <= 0) return;
        setTransport('poll');
        pollRef.current = setInterval(pollOnce, pollInterval);
    }, [pollOnce, pollInterval]);

    const refetch = useCallback(() => pollOnce(), [pollOnce]);

    useEffect(() => {
        if (!jobId || !enabled) return undefined;

        // Reset per-job state (the hook may be reused as jobId changes on retry).
        stoppedRef.current = false;
        maxIdRef.current = 0;
        seenRef.current = new Set();
        setJob(null);
        setLines([]);
        setError(null);
        setLoading(true);

        let cancelled = false;

        // 1) Full snapshot boot.
        (async () => {
            try {
                const data = await api.getDeploymentJob(jobId, true, includePlan);
                if (cancelled) return;
                const snapshot = data?.job;
                if (snapshot?.logs) mergeLines(snapshot.logs);
                applyJob(snapshot);
            } catch (err) {
                if (!cancelled) {
                    setError(err?.data?.error || err?.message || 'Deployment job not found');
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();

        // 2) Live socket path, with a graceful fall back to polling.
        socketService.connect();

        const resyncAndSubscribe = () => {
            if (stoppedRef.current) return;
            setTransport('socket');
            stopPolling();
            // Re-sync any rows emitted while we were disconnected, THEN trust the
            // stream (dedupe makes overlapping ids harmless).
            api.getDeploymentJobLogs(jobId, maxIdRef.current || null)
                .then((res) => mergeLines(res?.logs || []))
                .catch(() => {});
            socketService.subscribeDeploy(jobId);
        };

        const onDeployLog = (payload) => {
            if (payload?.job_id && String(payload.job_id) !== String(jobId)) return;
            mergeLines(payload?.lines || []);
        };
        const onDeployStatus = (payload) => {
            if (payload?.job_id && String(payload.job_id) !== String(jobId)) return;
            if (payload?.status) {
                applyJob(payload.status);
                if (TERMINAL.has(payload.status.status)) {
                    socketService.unsubscribeDeploy(jobId);
                    stopPolling();
                }
            }
        };

        if (socketService.socket?.connected) resyncAndSubscribe();
        const unsubConnect = socketService.on('connected', resyncAndSubscribe);
        const unsubDisconnect = socketService.on('disconnected', () => {
            if (!stoppedRef.current) startPolling();
        });
        const unsubLog = socketService.on('deploy_log', onDeployLog);
        const unsubStatus = socketService.on('deploy_status', onDeployStatus);

        // If the socket never connects, poll.
        const grace = setTimeout(() => {
            if (!socketService.socket?.connected && !stoppedRef.current) startPolling();
        }, SOCKET_GRACE_MS);

        return () => {
            cancelled = true;
            clearTimeout(grace);
            unsubConnect();
            unsubDisconnect();
            unsubLog();
            unsubStatus();
            socketService.unsubscribeDeploy(jobId);
            stopPolling();
        };
    }, [jobId, enabled, includePlan, mergeLines, applyJob, startPolling, stopPolling]);

    const isLive = !!job && !TERMINAL.has(job.status);

    return { job, lines, isLive, transport, error, loading, refetch };
}
