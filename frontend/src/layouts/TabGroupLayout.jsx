import { useState, useMemo } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { PageTopbar } from '@/components/ds';

// Generic shell for a PageTopbar tab group (Servers, Domains, Services, Files,
// Monitoring, Marketplace, …). A parent route renders the PageTopbar + routed
// sub-nav ONCE and swaps only the content below, so the tabs behave like real
// tabs — no full-page remount — and the matching sidebar item stays lit (see
// sidebarItems.js `matchPrefixes`). Child pages render no top bar of their own;
// they publish their own top-bar actions via the useTopbarActions() hook.
//
//   <Route element={<TabGroupLayout tabs={DOMAIN_TABS} />}>
//       <Route path="domains" element={<Domains />} />
//       <Route path="dns" element={<DNSZones />} />
//       <Route path="ssl" element={<SSLCertificates />} />
//   </Route>
function matchTab(tab, path) {
    if (tab.end) return path === tab.to;
    // Segment-aware so "/fleet" doesn't swallow "/fleet-monitor".
    return path === tab.to || path.startsWith(tab.to + '/');
}

export default function TabGroupLayout({ tabs }) {
    const location = useLocation();
    const [actions, setActions] = useState(null);

    // Title + icon mirror the active tab so the header always matches the lit
    // sub-nav item.
    const active = useMemo(
        () => tabs.find((t) => matchTab(t, location.pathname)) || tabs[0],
        [tabs, location.pathname]
    );

    return (
        <div className="page-container page-container--full-bleed sk-tabgroup">
            <PageTopbar
                icon={active.icon}
                title={active.label}
                tabs={tabs}
                actions={actions}
            />
            <div className="sk-tabgroup__content">
                <Outlet context={{ setTopbarActions: setActions }} />
            </div>
        </div>
    );
}
