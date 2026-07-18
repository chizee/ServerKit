// Web Analytics (serverkit-analytics) UI, contributed through the extension
// system. Fully self-contained. After sync this folder lives at
// frontend/src/plugins/serverkit-analytics/, so host '@/…' aliases resolve.
//
// plugin.json maps both /analytics and /analytics/:tab to AnalyticsPage (the
// tabbed dashboard). Resolved by NAMED export.
export { AnalyticsPage } from './components/AnalyticsPage.jsx';

// No default export on purpose: PluginLoader auto-renders any plugin default
// export globally. The route contributions resolve the named export.
