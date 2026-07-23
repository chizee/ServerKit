import { Check, Loader2, X, Circle } from 'lucide-react';

// Per-step duration formatter (seconds -> "3s" / "1m 4s").
const fmtSeconds = (s) => {
    if (s == null) return '';
    if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s % 60)}s`;
};

const STATE_ICON = {
    done: Check,
    running: Loader2,
    failed: X,
    pending: Circle,
};

// Left-hand checklist of the job plan: ✓ with duration when done, spinner on the
// current step, ✗ on the failed step, ○ pending. Clicking a step scrolls the log
// pane to that step's first line (via onStepClick(index)).
export default function StepRail({ steps, onStepClick }) {
    if (!steps || steps.length === 0) return null;
    return (
        <ol className="deploy-console__rail" aria-label="Deployment steps">
            {steps.map((step) => {
                const Icon = STATE_ICON[step.state] || Circle;
                return (
                    <li
                        key={step.index}
                        className={`deploy-console__rail-item deploy-console__rail-item--${step.state}`}
                    >
                        <button
                            type="button"
                            className="deploy-console__rail-btn"
                            onClick={() => onStepClick?.(step.index)}
                            title={step.name}
                        >
                            <span className="deploy-console__rail-icon">
                                <Icon
                                    size={15}
                                    className={step.state === 'running' ? 'deploy-console__spin' : ''}
                                />
                            </span>
                            <span className="deploy-console__rail-name">{step.name}</span>
                            {step.seconds != null && (
                                <span className="deploy-console__rail-time">{fmtSeconds(step.seconds)}</span>
                            )}
                        </button>
                    </li>
                );
            })}
        </ol>
    );
}
