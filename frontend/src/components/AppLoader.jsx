import ServerKitLogo from './ServerKitLogo';

/**
 * Minimal full-screen initial loader shown while auth/setup state is resolved.
 * A centered ServerKit logo with a soft pulsing ring — clean for the ~1s
 * the user sees it on first paint.
 */
export function AppLoader() {
    return (
        <div className="app-loader">
            <div className="app-loader__stage" aria-busy="true" aria-label="Loading ServerKit">
                <div className="app-loader__ring" />
                <div className="app-loader__logo">
                    <ServerKitLogo width={52} height={52} />
                </div>
            </div>
            <span className="app-loader__label">Loading ServerKit</span>
        </div>
    );
}

export default AppLoader;
