import { ChevronRight, ChevronDown, Database, HardDrive, Box, Table2, Loader2, MoreHorizontal } from 'lucide-react';

// Icon per node kind / engine. Tint comes from `.is-<engine>` in SCSS.
function NodeIcon({ node }) {
    if (node.kind === 'engine' || node.kind === 'database') {
        if (node.engine === 'sqlite') return <HardDrive size={15} aria-hidden="true" />;
        if (node.engine === 'docker') return <Box size={15} aria-hidden="true" />;
        return <Database size={15} aria-hidden="true" />;
    }
    if (node.kind === 'app') return <Box size={15} aria-hidden="true" />;
    if (node.kind === 'table') return <Table2 size={14} aria-hidden="true" />;
    return <Database size={15} aria-hidden="true" />;
}

const STATUS_LABEL = { active: 'Running', inactive: 'Stopped', missing: 'Not installed' };

function matches(node, filter) {
    return !filter || node.label.toLowerCase().includes(filter.toLowerCase());
}

function TreeRow({ node, depth, expanded, childrenCache, loading, activeKey, selectedId, filter, handlers }) {
    const isOpen = expanded.has(node.id);
    const isLoading = loading.has(node.id);
    const kids = childrenCache.get(node.id);
    const hadError = kids === 'error';
    const childNodes = Array.isArray(kids) ? kids : [];
    const visibleChildren = childNodes.filter((c) => c.expandable || matches(c, filter));

    return (
        <li className="dbx-tree-node" role="none">
            <div
                className={`dbx-tree-row is-${node.engine || node.kind}`
                    + (selectedId === node.id ? ' is-selected' : '')
                    + (activeKey && activeKey === node.id ? ' is-active' : '')}
                style={{ paddingLeft: `${depth * 14 + 6}px` }}
                role="treeitem"
                aria-expanded={node.expandable ? isOpen : undefined}
                aria-selected={selectedId === node.id}
                tabIndex={0}
                onClick={() => handlers.onActivate(node)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handlers.onActivate(node); }
                    if (e.key === 'ArrowRight' && node.expandable && !isOpen) handlers.onToggle(node);
                    if (e.key === 'ArrowLeft' && node.expandable && isOpen) handlers.onToggle(node);
                }}
                onContextMenu={(e) => handlers.onContext(e, node)}
            >
                {node.expandable ? (
                    <button
                        type="button"
                        className="dbx-tree-chevron"
                        onClick={(e) => { e.stopPropagation(); handlers.onToggle(node); }}
                        aria-label={isOpen ? 'Collapse' : 'Expand'}
                        tabIndex={-1}
                    >
                        {isLoading
                            ? <Loader2 size={13} className="dbx-spin" aria-hidden="true" />
                            : isOpen ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                    </button>
                ) : (
                    <span className="dbx-tree-chevron dbx-tree-chevron--leaf" aria-hidden="true" />
                )}

                <span className="dbx-tree-icon"><NodeIcon node={node} /></span>
                <span className="dbx-tree-label">{node.label}</span>

                {node.kind === 'engine' && node.status && node.status !== 'available' && (
                    <span className={`dbx-tree-status is-${node.status}`}>
                        <span className="dbx-status-dot" aria-hidden="true" />
                        {STATUS_LABEL[node.status]}
                    </span>
                )}
                {node.kind === 'table' && node.rows != null && (
                    <span className="dbx-tree-badge">{node.rows.toLocaleString()}</span>
                )}
                {node.kind === 'database' && node.sizeText && (
                    <span className="dbx-tree-badge">{node.sizeText}</span>
                )}

                <button
                    type="button"
                    className="dbx-tree-more"
                    onClick={(e) => { e.stopPropagation(); handlers.onContext(e, node); }}
                    aria-label="Actions"
                    tabIndex={-1}
                >
                    <MoreHorizontal size={14} aria-hidden="true" />
                </button>
            </div>

            {node.expandable && isOpen && (
                <ul className="dbx-tree-children" role="group">
                    {isLoading && childNodes.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>Loading…</li>
                    )}
                    {hadError && (
                        <li className="dbx-tree-leaf-msg is-error" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>
                            Couldn&apos;t load. Right-click to retry.
                        </li>
                    )}
                    {!isLoading && !hadError && childNodes.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>Empty</li>
                    )}
                    {visibleChildren.map((child) => (
                        <TreeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            expanded={expanded}
                            childrenCache={childrenCache}
                            loading={loading}
                            activeKey={activeKey}
                            selectedId={selectedId}
                            filter={filter}
                            handlers={handlers}
                        />
                    ))}
                    {!isLoading && !hadError && childNodes.length > 0 && visibleChildren.length === 0 && (
                        <li className="dbx-tree-leaf-msg" style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>No match</li>
                    )}
                </ul>
            )}
        </li>
    );
}

export default function SourceTree({ roots, expanded, childrenCache, loading, activeKey, selectedId, filter, handlers }) {
    return (
        <ul className="dbx-tree" role="tree" aria-label="Database sources">
            {roots.map((node) => (
                <TreeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    expanded={expanded}
                    childrenCache={childrenCache}
                    loading={loading}
                    activeKey={activeKey}
                    selectedId={selectedId}
                    filter={filter}
                    handlers={handlers}
                />
            ))}
        </ul>
    );
}
