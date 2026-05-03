/**
 * Renders <Route> entries for each contributed route from active plugins.
 *
 * Used by App.jsx inside the authenticated dashboard branch — extension
 * routes are protected by the same PrivateRoute guard as core pages.
 *
 * A contributed route is { path, component, layout? }. We resolve
 * `component` against the plugin's index module exports. Routes whose
 * components don't resolve are silently skipped (logged in dev) so a
 * misconfigured plugin can't blow up the whole route tree.
 */
import { Route } from 'react-router-dom';
import { useContributions, resolveComponent } from './contributions';

function buildRoute(contrib, key) {
    const Component = resolveComponent(contrib.plugin, contrib.component);
    if (!Component) {
        if (import.meta.env.DEV) {
            console.warn(
                `[plugins] Cannot resolve component "${contrib.component}" `
                + `for plugin "${contrib.plugin}" (route ${contrib.path})`
            );
        }
        return null;
    }
    return (
        <Route
            key={key}
            path={contrib.path}
            element={<Component />}
        />
    );
}

// React Router v6 requires Route children to be static JSX siblings —
// returning a fragment of <Route>s from a function works because the
// parent <Routes> walks the tree.
export default function useExtensionRoutes() {
    const { routes } = useContributions();
    return (routes || [])
        .map((c, i) => buildRoute(c, `${c.plugin}:${c.path}:${i}`))
        .filter(Boolean);
}
