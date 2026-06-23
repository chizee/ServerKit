import React, { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Pill, SegControl } from '../ds';
import EmptyState from '../EmptyState';
import { Network } from 'lucide-react';

// Managed reverse-proxy stack panel for a server.
//
// Host nginx is the default (and the better choice for PHP/WordPress). This
// panel lets an operator opt into a Dockerized proxy — Traefik or Caddy —
// deployed as a Compose stack, preview the generated compose, edit a custom
// config snippet, and (best-effort) regenerate / restart the stack.

const PROXY_OPTIONS = [
    { value: 'nginx', label: 'Nginx', sub: 'Host default' },
    { value: 'traefik', label: 'Traefik', sub: 'Docker stack' },
    { value: 'caddy', label: 'Caddy', sub: 'Docker stack' },
];

const STATUS_KIND = {
    running: 'green',
    stopped: 'gray',
    error: 'red',
    unknown: 'amber',
};

const ProxyStackPanel = ({ serverId }) => {
    const toast = useToast();
    const [stack, setStack] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Local working state — the selected type may differ from the saved one
    // until the user clicks "Switch".
    const [selectedType, setSelectedType] = useState('nginx');
    const [snippet, setSnippet] = useState('');
    const [preview, setPreview] = useState(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getServerProxy(serverId);
            setStack(data);
            setSelectedType(data.proxy_type || 'nginx');
            setSnippet(data.custom_snippet || '');
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load proxy configuration');
        } finally {
            setLoading(false);
        }
    }, [serverId]);

    useEffect(() => {
        load();
    }, [load]);

    // Refresh the compose preview whenever the selected type changes.
    const loadPreview = useCallback(async (proxyType) => {
        try {
            const data = await api.getServerProxyComposePreview(serverId, { proxyType });
            setPreview(data);
        } catch (err) {
            console.error('Failed to load compose preview:', err);
            setPreview(null);
        }
    }, [serverId]);

    useEffect(() => {
        loadPreview(selectedType);
    }, [selectedType, loadPreview]);

    const isDirtyType = stack && selectedType !== stack.proxy_type;
    const isDirtySnippet = stack && snippet !== (stack.custom_snippet || '');

    async function handleSwitch() {
        setBusy(true);
        try {
            await api.switchServerProxy(serverId, selectedType);
            toast.success(`Switched to ${selectedType}`);
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to switch proxy');
        } finally {
            setBusy(false);
        }
    }

    async function handleSaveSnippet() {
        setBusy(true);
        try {
            await api.configureServerProxy(serverId, { custom_snippet: snippet });
            toast.success('Custom snippet saved');
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to save snippet');
        } finally {
            setBusy(false);
        }
    }

    async function handleRegenerate() {
        setBusy(true);
        try {
            const res = await api.regenerateServerProxy(serverId);
            if (res.success) {
                toast.success(res.reloaded ? 'Config regenerated and reloaded' : 'Config regenerated');
            } else {
                toast.error(res.error || 'Regenerate failed');
            }
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to regenerate config');
        } finally {
            setBusy(false);
        }
    }

    async function handleDeploy() {
        setBusy(true);
        try {
            const res = await api.configureServerProxy(serverId, {
                proxy_type: selectedType,
                deploy: true,
            });
            const deploy = res.deploy;
            if (deploy && deploy.success === false) {
                toast.error(deploy.error || 'Deploy failed (best-effort)');
            } else {
                toast.success('Stack deployed');
            }
            await load();
        } catch (err) {
            toast.error(err.message || 'Failed to deploy stack');
        } finally {
            setBusy(false);
        }
    }

    if (loading) {
        return <EmptyState loading title="Loading proxy configuration" />;
    }

    if (error) {
        return (
            <div className="proxy-panel">
                <div className="proxy-panel__error">{error}</div>
                <Button variant="outline" onClick={load}>Retry</Button>
            </div>
        );
    }

    const isNginx = selectedType === 'nginx';
    const savedIsNginx = stack?.proxy_type === 'nginx';

    return (
        <div className="proxy-panel">
            <header className="proxy-panel__header">
                <div className="proxy-panel__title">
                    <Network size={18} />
                    <h3>Reverse Proxy</h3>
                </div>
                <div className="proxy-panel__status">
                    <span className="proxy-panel__status-label">Status</span>
                    <Pill kind={STATUS_KIND[stack?.status] || 'gray'}>
                        {savedIsNginx ? 'host nginx' : (stack?.status || 'unknown')}
                    </Pill>
                </div>
            </header>

            <p className="proxy-panel__hint">
                Host Nginx is the default and is recommended for PHP/WordPress. You can
                opt into a Dockerized Traefik or Caddy proxy deployed as a Compose stack.
            </p>

            <section className="proxy-panel__section">
                <label className="proxy-panel__label">Proxy type</label>
                <SegControl
                    options={PROXY_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    value={selectedType}
                    onChange={setSelectedType}
                />
                <div className="proxy-panel__actions">
                    <Button onClick={handleSwitch} disabled={!isDirtyType || busy}>
                        {isDirtyType ? `Switch to ${selectedType}` : 'No change'}
                    </Button>
                    {!isNginx && (
                        <Button variant="outline" onClick={handleDeploy} disabled={busy}>
                            Deploy / Restart
                        </Button>
                    )}
                    {!savedIsNginx && (
                        <Button variant="outline" onClick={handleRegenerate} disabled={busy}>
                            Regenerate config
                        </Button>
                    )}
                </div>
            </section>

            {!isNginx && (
                <section className="proxy-panel__section">
                    <label className="proxy-panel__label">Compose preview</label>
                    {preview?.compose ? (
                        <pre className="proxy-panel__code" aria-label="docker-compose preview">
                            {preview.compose}
                        </pre>
                    ) : (
                        <div className="proxy-panel__empty">No compose generated for this type.</div>
                    )}
                </section>
            )}

            {!isNginx && (
                <section className="proxy-panel__section">
                    <label className="proxy-panel__label">Custom config snippet</label>
                    <Textarea
                        rows={6}
                        value={snippet}
                        onChange={(e) => setSnippet(e.target.value)}
                        placeholder="Appended to the generated proxy config (Caddyfile / Traefik dynamic)."
                        className="font-mono"
                    />
                    <div className="proxy-panel__actions">
                        <Button
                            variant="outline"
                            onClick={handleSaveSnippet}
                            disabled={!isDirtySnippet || busy}
                        >
                            Save snippet
                        </Button>
                    </div>
                </section>
            )}

            {isNginx && (
                <EmptyState
                    icon={Network}
                    title="Host Nginx is active"
                    description="The host's Nginx is handling reverse proxying. Switch to Traefik or Caddy above to run a managed Docker proxy stack instead."
                />
            )}
        </div>
    );
};

export default ProxyStackPanel;
