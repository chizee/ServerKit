import { Copy, Download, Search } from 'lucide-react';

const LEVELS = ['all', 'info', 'warn', 'error', 'debug'];

// Log toolbar: follow / wrap / timestamps toggles, a level filter, a client-side
// search box, plus copy-all and download-.txt actions.
export default function ConsoleToolbar({
    follow, onToggleFollow,
    wrap, onToggleWrap,
    timestamps, onToggleTimestamps,
    level, onLevelChange,
    search, onSearchChange,
    onCopy, onDownload,
}) {
    return (
        <div className="deploy-console__toolbar">
            <div className="deploy-console__toolbar-group">
                <button
                    type="button"
                    className={`deploy-console__toggle ${follow ? 'is-active' : ''}`}
                    onClick={onToggleFollow}
                    aria-pressed={follow}
                >
                    Follow
                </button>
                <button
                    type="button"
                    className={`deploy-console__toggle ${wrap ? 'is-active' : ''}`}
                    onClick={onToggleWrap}
                    aria-pressed={wrap}
                >
                    Wrap
                </button>
                <button
                    type="button"
                    className={`deploy-console__toggle ${timestamps ? 'is-active' : ''}`}
                    onClick={onToggleTimestamps}
                    aria-pressed={timestamps}
                >
                    Timestamps
                </button>
                <label className="deploy-console__level">
                    <span className="sr-only">Log level</span>
                    <select value={level} onChange={(e) => onLevelChange(e.target.value)}>
                        {LEVELS.map((l) => (
                            <option key={l} value={l}>{l === 'all' ? 'All levels' : l}</option>
                        ))}
                    </select>
                </label>
            </div>

            <div className="deploy-console__toolbar-group">
                <div className="deploy-console__search">
                    <Search size={14} />
                    <input
                        type="text"
                        placeholder="Search logs…"
                        value={search}
                        onChange={(e) => onSearchChange(e.target.value)}
                    />
                </div>
                <button type="button" className="deploy-console__toggle" onClick={onCopy} title="Copy all logs">
                    <Copy size={14} /> Copy
                </button>
                <button type="button" className="deploy-console__toggle" onClick={onDownload} title="Download logs as .txt">
                    <Download size={14} /> Download
                </button>
            </div>
        </div>
    );
}
