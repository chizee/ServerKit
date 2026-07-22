import { useContext } from 'react';
import { AlertTriangle, RefreshCw, Copy, Sparkles } from 'lucide-react';
import { AIContext } from '../../contexts/AIContext';

// Pinned failure card (plan 51 §1.1): failed step name, the persisted failure
// tail (the real reason, not a summary), the one-line error, a plain-language
// hint when a heuristic matched, and actions: Retry / Copy error / Ask AI.
export default function ErrorCard({ failedStepName, failureTail, hint, errorMessage, onRetry, retrying }) {
    // Read the AI drawer context directly (null when no AIProvider is mounted),
    // so the hook is called unconditionally and the "Ask AI" button degrades
    // gracefully.
    const ai = useContext(AIContext);

    const tailText = Array.isArray(failureTail) ? failureTail.join('\n') : (failureTail || '');

    const copyError = () => {
        const blob = [
            failedStepName ? `Failed step: ${failedStepName}` : null,
            errorMessage ? `Error: ${errorMessage}` : null,
            tailText ? `\n${tailText}` : null,
        ].filter(Boolean).join('\n');
        navigator.clipboard?.writeText(blob);
    };

    const askAI = () => {
        if (!ai?.open) return;
        const prompt = [
            'A deployment on my server failed. Here is the failing step and the tail',
            'of the build output — explain what went wrong and how to fix it:\n',
            failedStepName ? `Failed step: ${failedStepName}` : '',
            errorMessage ? `Error: ${errorMessage}` : '',
            tailText ? `\nOutput:\n${tailText}` : '',
        ].join('\n');
        ai.open(prompt);
    };

    return (
        <div className="deploy-console__error" role="alert">
            <div className="deploy-console__error-head">
                <AlertTriangle size={18} />
                <div>
                    <strong>Deployment failed{failedStepName ? ` at "${failedStepName}"` : ''}</strong>
                    {errorMessage && <p className="deploy-console__error-msg">{errorMessage}</p>}
                </div>
            </div>

            {hint && (
                <p className="deploy-console__error-hint">
                    <Sparkles size={14} /> {hint}
                </p>
            )}

            {tailText && (
                <pre className="deploy-console__error-tail">{tailText}</pre>
            )}

            <div className="deploy-console__error-actions">
                <button type="button" className="deploy-console__btn deploy-console__btn--primary" onClick={onRetry} disabled={retrying}>
                    <RefreshCw size={14} className={retrying ? 'deploy-console__spin' : ''} />
                    {retrying ? 'Retrying…' : 'Retry deploy'}
                </button>
                <button type="button" className="deploy-console__btn" onClick={copyError}>
                    <Copy size={14} /> Copy error
                </button>
                {ai?.open && (
                    <button type="button" className="deploy-console__btn" onClick={askAI}>
                        <Sparkles size={14} /> Ask AI
                    </button>
                )}
            </div>
        </div>
    );
}
