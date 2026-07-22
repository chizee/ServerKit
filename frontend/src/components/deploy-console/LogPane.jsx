import { useEffect, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';

// Monospace console surface. Auto-scrolls while "follow" is on; disengages when
// the user scrolls up and re-engages via a "Jump to live" chip. Lines carry a
// data-step attribute so the step rail can scroll a step into view.
export default function LogPane({ lines, wrap, timestamps, follow, onFollowChange, scrollToStep }) {
    const paneRef = useRef(null);
    const endRef = useRef(null);
    const [showJump, setShowJump] = useState(false);

    // Follow: keep pinned to the bottom as new lines arrive.
    useEffect(() => {
        if (follow && paneRef.current) {
            paneRef.current.scrollTop = paneRef.current.scrollHeight;
            setShowJump(false);
        }
    }, [lines, follow]);

    // Scroll a given step's first line into view when the rail is clicked.
    useEffect(() => {
        if (scrollToStep == null || !paneRef.current) return;
        const el = paneRef.current.querySelector(`[data-step="${scrollToStep}"]`);
        if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, [scrollToStep]);

    const onScroll = () => {
        const pane = paneRef.current;
        if (!pane) return;
        const atBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
        if (!atBottom && follow) onFollowChange(false);
        setShowJump(!atBottom);
    };

    const jumpToLive = () => {
        onFollowChange(true);
        if (paneRef.current) paneRef.current.scrollTop = paneRef.current.scrollHeight;
        setShowJump(false);
    };

    let lastStep = null;

    return (
        <div className="deploy-console__logwrap">
            <div
                ref={paneRef}
                className={`deploy-console__log ${wrap ? 'deploy-console__log--wrap' : ''}`}
                onScroll={onScroll}
                role="log"
                aria-live="polite"
            >
                {lines.length === 0 ? (
                    <div className="deploy-console__log-empty">Waiting for output…</div>
                ) : (
                    lines.map((ln, i) => {
                        const isNewStep = ln.step_index != null && ln.step_index !== lastStep;
                        if (ln.step_index != null) lastStep = ln.step_index;
                        const ts = timestamps && ln.ts
                            ? new Date(ln.ts).toLocaleTimeString()
                            : (timestamps && ln.created_at ? new Date(ln.created_at).toLocaleTimeString() : '');
                        return (
                            <div
                                key={ln.id ?? `i${i}`}
                                className={`deploy-console__line deploy-console__line--${ln.level || 'info'}`}
                                data-step={isNewStep ? ln.step_index : undefined}
                            >
                                {timestamps && <span className="deploy-console__line-ts">{ts}</span>}
                                <span className="deploy-console__line-msg">{ln.message}</span>
                            </div>
                        );
                    })
                )}
                <div ref={endRef} />
            </div>
            {showJump && (
                <button type="button" className="deploy-console__jump" onClick={jumpToLive}>
                    <ArrowDown size={14} /> Jump to live
                </button>
            )}
        </div>
    );
}
