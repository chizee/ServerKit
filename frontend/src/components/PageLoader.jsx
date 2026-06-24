import { Spinner } from './Spinner';

/**
 * Full-page loader for tab-group pages.
 * Centers a spinner inside the standard tab-group inner area.
 */
export function PageLoader({ className = '' }) {
    return (
        <div className={`sk-tabgroup__inner ${className}`.trim()}>
            <Spinner />
        </div>
    );
}

export default PageLoader;
