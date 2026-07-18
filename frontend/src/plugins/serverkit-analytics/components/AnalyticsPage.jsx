// Web Analytics dashboard (serverkit-analytics). Placeholder scaffold — the six
// tabs (Overview / Pages / Referrers / Devices / Realtime / Sites) land in
// Phase 4. Kept minimal so the frontend builds from Phase 0.
import { PageTopbar } from '@/components/ds';

export function AnalyticsPage() {
    return (
        <div className="analytics-page">
            <PageTopbar title="Web Analytics" />
            <div className="sk-tabgroup__inner">
                <p>Web Analytics is installing. The dashboard will appear here.</p>
            </div>
        </div>
    );
}
