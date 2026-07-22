import { useEffect, useState } from 'react';
import { Link2, Unlink } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { ConfirmDialog } from '../ConfirmDialog';
import StatusBadge from '../StatusBadge';
import { InfoList, InfoItem } from '../InfoList';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const POLL_INTERVAL = 5000;

function formatTimestamp(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

// "Linked Panel" — the inverse of Add Server: link THIS panel to a master
// ServerKit so the master can deploy apps here as if the Go agent were
// installed. Polls the link status while visible so the connection badge
// flips to Connected live.
const LinkedPanelCard = () => {
    const toast = useToast();
    const [status, setStatus] = useState(null); // null = still loading
    const [masterUrl, setMasterUrl] = useState('');
    const [token, setToken] = useState('');
    const [name, setName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [linkError, setLinkError] = useState('');
    const [unlinkOpen, setUnlinkOpen] = useState(false);

    async function loadStatus({ silent = false } = {}) {
        try {
            const data = await api.getLinkedPanel();
            setStatus(data);
        } catch (err) {
            if (!silent) toast.error(err?.data?.error || err.message || 'Failed to load linked panel status');
        }
    }

    useEffect(() => {
        loadStatus();
        const interval = setInterval(() => loadStatus({ silent: true }), POLL_INTERVAL);
        return () => clearInterval(interval);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    async function handleLink(e) {
        e.preventDefault();
        setLinkError('');
        setSubmitting(true);
        try {
            const result = await api.linkPanel({
                master_url: masterUrl.trim(),
                registration_token: token.trim(),
                name: name.trim() || undefined,
            });
            toast.success('Panel linked to master');
            setStatus(result.status || { linked: true, master_url: masterUrl.trim() });
            setToken('');
        } catch (err) {
            setLinkError(err?.data?.error || err.message || 'Failed to link panel');
        } finally {
            setSubmitting(false);
        }
    }

    async function handleUnlink() {
        try {
            await api.unlinkPanel();
            toast.success('Panel unlinked');
            setUnlinkOpen(false);
            setStatus({ linked: false });
        } catch (err) {
            toast.error(err?.data?.error || err.message || 'Failed to unlink panel');
        }
    }

    const linked = Boolean(status?.linked);

    return (
        <section className="linked-panel-card">
            <div className="linked-panel-card__header">
                <Link2 size={16} />
                <div>
                    <h3>Linked Panel</h3>
                    <p className="text-muted">
                        Link this panel to a master ServerKit so it can manage this server — no separate agent install needed.
                    </p>
                </div>
                {linked && (
                    <StatusBadge status={status.connected ? 'connected' : 'disconnected'} />
                )}
            </div>

            {status === null ? (
                <p className="text-muted">Loading link status…</p>
            ) : !linked ? (
                <form className="linked-panel-card__form" onSubmit={handleLink}>
                    <p className="text-muted">
                        Generate a registration token on the master: Servers → Add Server / regenerate token.
                    </p>
                    {linkError && <div className="alert alert-danger">{linkError}</div>}
                    <div className="form-group">
                        <label>Master URL *</label>
                        <Input
                            type="url"
                            value={masterUrl}
                            onChange={(e) => setMasterUrl(e.target.value)}
                            placeholder="https://panel.example.com"
                            required
                        />
                    </div>
                    <div className="form-group">
                        <label>Registration token *</label>
                        <Input
                            type="password"
                            value={token}
                            onChange={(e) => setToken(e.target.value)}
                            placeholder="Token generated on the master"
                            required
                        />
                    </div>
                    <div className="form-group">
                        <label>Display name</label>
                        <Input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Optional — how this server appears on the master"
                        />
                    </div>
                    <div className="linked-panel-card__actions">
                        <Button type="submit" disabled={submitting}>
                            <Link2 size={14} /> {submitting ? 'Linking…' : 'Link panel'}
                        </Button>
                    </div>
                </form>
            ) : (
                <div className="linked-panel-card__status">
                    <InfoList>
                        <InfoItem label="Master" value={status.master_url} mono />
                        <InfoItem
                            label="Remote server"
                            value={status.remote_server_name
                                ? `${status.remote_server_name}${status.remote_server_id ? ` (#${status.remote_server_id})` : ''}`
                                : (status.remote_server_id ? `#${status.remote_server_id}` : '—')}
                        />
                        <InfoItem label="Agent ID" value={status.agent_id} mono />
                        <InfoItem label="Linked since" value={formatTimestamp(status.created_at)} />
                        <InfoItem label="Last heartbeat" value={formatTimestamp(status.last_heartbeat_at)} />
                    </InfoList>
                    {status.last_error && (
                        <div className="alert alert-danger">
                            <strong>Connection error:</strong> {status.last_error}
                        </div>
                    )}
                    <div className="linked-panel-card__actions">
                        <Button type="button" variant="destructive" onClick={() => setUnlinkOpen(true)}>
                            <Unlink size={14} /> Unlink
                        </Button>
                    </div>
                </div>
            )}

            <ConfirmDialog
                isOpen={unlinkOpen}
                title="Unlink from master panel?"
                message={`This server will stop being manageable by ${status?.master_url || 'the master panel'}. The link credentials are removed from this panel.`}
                confirmText="Unlink"
                variant="danger"
                onConfirm={handleUnlink}
                onCancel={() => setUnlinkOpen(false)}
            />
        </section>
    );
};

export default LinkedPanelCard;
