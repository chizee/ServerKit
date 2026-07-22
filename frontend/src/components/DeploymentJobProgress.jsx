import { useEffect, useRef, useState } from 'react';
import api from '../services/api';

// Give up after this many consecutive failed polls — a transient network blip
// shouldn't kill the watcher, but a permanently unreachable job must not spin
// forever.
const MAX_CONSECUTIVE_POLL_ERRORS = 5;

// Shared "watch it come up live" panel: polls a DeploymentJob and renders its
// status, progress bar, current step and log output. Used by the Templates
// install modal and the service Logs tab so every deploy flow behaves the same.
//
// Terminal handling:
// - status 'succeeded'  -> onSuccess(job)
// - status 'failed'     -> onFailure(job.error_message)
// - too many poll errors-> onFailure(last poll error)
// - timeoutMs elapsed   -> onFailure('timed out' message)
export default function DeploymentJobProgress({
    jobId,
    onSuccess,
    onFailure,
    pollInterval = 1500,
    timeoutMs = 600000,
}) {
    const [job, setJob] = useState(null);
    const [pollError, setPollError] = useState(null); // { message, attempts }
    // Keep callbacks in refs so a re-rendering parent doesn't restart polling.
    const onSuccessRef = useRef(onSuccess);
    const onFailureRef = useRef(onFailure);
    onSuccessRef.current = onSuccess;
    onFailureRef.current = onFailure;

    useEffect(() => {
        if (!jobId) return undefined;
        let stopped = false;
        let consecutiveErrors = 0;
        let intervalId = null;
        let timeoutId = null;

        const finish = (cb, arg) => {
            if (stopped) return;
            stopped = true;
            if (intervalId) clearInterval(intervalId);
            if (timeoutId) clearTimeout(timeoutId);
            cb(arg);
        };

        async function poll() {
            try {
                const data = await api.getDeploymentJob(jobId, true);
                if (stopped) return;
                consecutiveErrors = 0;
                setPollError(null);
                const latest = data.job;
                setJob(latest);
                if (latest.status === 'succeeded') {
                    finish(onSuccessRef.current, latest);
                } else if (latest.status === 'failed') {
                    finish(onFailureRef.current, latest.error_message || 'Deployment failed');
                }
            } catch (err) {
                if (stopped) return;
                consecutiveErrors += 1;
                const message = err?.data?.error || err?.message || 'Failed to poll deployment status';
                if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
                    finish(onFailureRef.current, `Lost contact with the deployment job: ${message}`);
                } else {
                    setPollError({ message, attempts: consecutiveErrors });
                }
            }
        }

        poll();
        intervalId = setInterval(poll, pollInterval);
        timeoutId = setTimeout(() => {
            const minutes = Math.round(timeoutMs / 60000);
            finish(onFailureRef.current, `Deployment timed out after ${minutes} minutes without reaching a final state`);
        }, timeoutMs);

        return () => {
            stopped = true;
            if (intervalId) clearInterval(intervalId);
            if (timeoutId) clearTimeout(timeoutId);
        };
    }, [jobId, pollInterval, timeoutMs]);

    const status = job?.status || 'pending';
    const progress = job?.progress_percent ?? 0;
    const logs = job?.logs || [];

    return (
        <div className="deployment-job-progress">
            <div className="deployment-progress">
                <div className="deployment-progress-track">
                    <div
                        className="deployment-progress-fill"
                        style={{ width: `${progress}%` }}
                    />
                </div>
                <span>{status} {progress}%</span>
            </div>
            {job?.current_step_name && (
                <p className="deployment-job-progress__step text-muted">
                    Current step: {job.current_step_name}
                </p>
            )}
            {pollError && (
                <div className="alert alert-warning">
                    Trouble reaching the deployment job (attempt {pollError.attempts}/{MAX_CONSECUTIVE_POLL_ERRORS}): {pollError.message}. Retrying…
                </div>
            )}
            <pre className="log-viewer">
                {logs.map(log => {
                    const prefix = log.step_index ? `[${log.step_index}] ` : '';
                    return `${prefix}${log.message}`;
                }).join('\n') || 'Waiting for deployment logs...'}
            </pre>
        </div>
    );
}
