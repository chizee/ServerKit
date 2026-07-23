import { Link } from 'react-router-dom';
import { CheckCircle2, ExternalLink, LayoutGrid, ScrollText } from 'lucide-react';

const fmtSeconds = (s) => {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s % 60)}s`;
};

// Completion banner (plan 51 §1.1): total duration, per-step timings, and the
// payoff actions — Open app (when a live URL exists), View service, View
// runtime logs.
export default function SuccessBanner({ job, appUrl }) {
    const timings = job?.result?.step_timings || [];
    const appId = job?.app_id;

    return (
        <div className="deploy-console__success">
            <div className="deploy-console__success-head">
                <CheckCircle2 size={20} />
                <div>
                    <strong>Deployed successfully</strong>
                    <span className="deploy-console__success-dur">
                        Completed in {fmtSeconds(job?.duration)}
                    </span>
                </div>
            </div>

            {timings.length > 0 && (
                <ul className="deploy-console__success-timings">
                    {timings.map((t) => (
                        <li key={t.index}>
                            <span>{t.name || `Step ${t.index}`}</span>
                            <span>{fmtSeconds(t.seconds)}</span>
                        </li>
                    ))}
                </ul>
            )}

            <div className="deploy-console__success-actions">
                {appUrl && (
                    <a className="deploy-console__btn deploy-console__btn--primary" href={appUrl} target="_blank" rel="noreferrer">
                        <ExternalLink size={14} /> Open app
                    </a>
                )}
                {appId && (
                    <Link className="deploy-console__btn" to={`/services/${appId}`}>
                        <LayoutGrid size={14} /> View service
                    </Link>
                )}
                {appId && (
                    <Link className="deploy-console__btn" to={`/services/${appId}/logs`}>
                        <ScrollText size={14} /> View runtime logs
                    </Link>
                )}
            </div>
        </div>
    );
}
