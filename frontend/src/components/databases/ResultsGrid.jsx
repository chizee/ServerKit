import { useMemo, useState } from 'react';
import { ChevronUp, ChevronDown, Database } from 'lucide-react';
import EmptyState from '../EmptyState';

// Renders a query/data result set: columns + row arrays. Sorting is client-side
// over the rows already returned (a page), matching the old QueryRunner.
export default function ResultsGrid({ columns, rows, loading, error, emptyTitle = 'No rows', emptyDescription }) {
    const [sort, setSort] = useState({ col: null, dir: 'asc' });

    const sortedRows = useMemo(() => {
        if (!rows || sort.col === null) return rows || [];
        const dir = sort.dir === 'asc' ? 1 : -1;
        return [...rows].sort((a, b) => {
            const av = a[sort.col];
            const bv = b[sort.col];
            if (av === null && bv === null) return 0;
            if (av === null) return 1;
            if (bv === null) return -1;
            const an = Number(av);
            const bn = Number(bv);
            if (!Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== '') {
                return (an - bn) * dir;
            }
            return String(av).localeCompare(String(bv)) * dir;
        });
    }, [rows, sort]);

    function toggleSort(idx) {
        setSort((prev) => ({
            col: idx,
            dir: prev.col === idx && prev.dir === 'asc' ? 'desc' : 'asc',
        }));
    }

    if (loading) {
        return (
            <div className="dbx-grid-status">
                <EmptyState loading title="Running query…" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="dbx-grid-error" role="alert">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" fill="none" strokeWidth="2" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <pre>{error}</pre>
            </div>
        );
    }

    if (!columns || columns.length === 0) {
        return (
            <div className="dbx-grid-status">
                <EmptyState icon={Database} title={emptyTitle} description={emptyDescription} />
            </div>
        );
    }

    return (
        <div className="dbx-grid-scroll">
            <table className="dbx-grid">
                <thead>
                    <tr>
                        <th className="dbx-grid-rownum" aria-hidden="true" />
                        {columns.map((col, idx) => (
                            <th
                                key={idx}
                                scope="col"
                                aria-sort={sort.col === idx ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                            >
                                <button type="button" className="dbx-grid-th" onClick={() => toggleSort(idx)}>
                                    <span className="dbx-grid-th-name">{col}</span>
                                    {sort.col === idx && (
                                        sort.dir === 'asc'
                                            ? <ChevronUp size={13} aria-hidden="true" />
                                            : <ChevronDown size={13} aria-hidden="true" />
                                    )}
                                </button>
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {sortedRows.map((row, rowIdx) => (
                        <tr key={rowIdx}>
                            <td className="dbx-grid-rownum">{rowIdx + 1}</td>
                            {row.map((cell, cellIdx) => (
                                <td key={cellIdx} className={cell === null ? 'is-null' : undefined} title={cell === null ? 'NULL' : String(cell)}>
                                    {cell === null ? 'NULL' : String(cell)}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
