import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import api from '../services/api';
import socketService from '../services/socket';

// A small global "deploy in progress" pill: while any deployment job is
// pending/running it appears (bottom-left) so you can navigate away mid-deploy
// and always find your way back to the live Deploy Console (plan 51 §1.3).
// Driven by a lightweight poll of GET /deployment-jobs?status=running, refreshed
// on socket reconnect and on any deploy_status event that flows through.
const POLL_MS = 6000;

export default function DeployPill() {
    const [active, setActive] = useState([]);

    const refresh = useCallback(async () => {
        try {
            const [running, pending] = await Promise.all([
                api.getDeploymentJobs({ status: 'running', limit: 20 }),
                api.getDeploymentJobs({ status: 'pending', limit: 20 }),
            ]);
            const jobs = [...(running?.jobs || []), ...(pending?.jobs || [])];
            setActive(jobs);
        } catch {
            // Silent — the pill is a convenience, not critical chrome.
        }
    }, []);

    useEffect(() => {
        refresh();
        const t = setInterval(refresh, POLL_MS);
        // React quickly to live status changes when a console elsewhere is streaming.
        const unsubStatus = socketService.on('deploy_status', refresh);
        const unsubConnect = socketService.on('connected', refresh);
        return () => {
            clearInterval(t);
            unsubStatus();
            unsubConnect();
        };
    }, [refresh]);

    if (active.length === 0) return null;

    const count = active.length;
    const to = count === 1 ? `/deployments/${active[0].id}` : '/deployments';
    const label = count === 1 ? '1 deploy running' : `${count} deploys running`;

    return (
        <Link to={to} className="deploy-pill" title="Open the Deploy Console">
            <Loader2 size={14} className="deploy-pill__spin" />
            <span>{label}</span>
        </Link>
    );
}
