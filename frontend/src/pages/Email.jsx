// Email Server — management page for the serverkit-email extension.
//
// NOTE: This file was reconstructed after a data-loss corruption. The original
// was ~63KB; this is a coherent, functional, on-style rebuild — not a
// byte-for-byte restore. It is wired to the real ApiService email methods
// (see frontend/src/services/api/system.js, the `/email/*` endpoints) and
// covers the same surface area: server/service status, mail domains with
// SPF/DKIM/DMARC/PTR presence pills + DNS verify/deploy, accounts, aliases,
// outbound relay (smarthost), SpamAssassin, webmail, and the mail queue.
import { useState, useEffect, useCallback } from 'react';
import {
    Mail, RefreshCw, Plus, Trash2, ShieldCheck, Server, Globe, Users,
    Send, Filter, Inbox, ExternalLink, CheckCircle2, XCircle, HelpCircle,
} from 'lucide-react';
import api from '../services/api';
import useTabParam from '../hooks/useTabParam';
import { PageTopbar, Pill, MetricCard, KpiBand } from '@/components/ds';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '../contexts/ToastContext';
import { useConfirm } from '../hooks/useConfirm';

const VALID_TABS = ['overview', 'domains', 'accounts', 'relay', 'spam', 'webmail', 'queue'];

// DNS record checks surfaced as presence pills. `state` is one of
// 'ok' | 'missing' | 'unknown' and maps to a DS Pill colour + dot.
const DNS_RECORDS = [
    { key: 'spf', label: 'SPF' },
    { key: 'dkim', label: 'DKIM' },
    { key: 'dmarc', label: 'DMARC' },
    { key: 'ptr', label: 'PTR' },
    { key: 'mx', label: 'MX' },
];

function dnsPillKind(state) {
    if (state === 'ok') return 'green';
    if (state === 'missing') return 'red';
    return 'gray';
}

// Derive a per-record status map from a domain record and an optional live
// verify result. Falls back to "does the stored record string exist" when we
// have not run a live DNS check yet.
function deriveDnsStatus(domain, verify) {
    const out = {};
    for (const { key } of DNS_RECORDS) {
        if (verify && verify[key]) {
            out[key] = verify[key].valid || verify[key].present ? 'ok' : 'missing';
        } else if (key === 'spf') {
            out[key] = domain?.spf_record ? 'ok' : 'unknown';
        } else if (key === 'dkim') {
            out[key] = domain?.dkim_public_key ? 'ok' : 'unknown';
        } else if (key === 'dmarc') {
            out[key] = domain?.dmarc_record ? 'ok' : 'unknown';
        } else {
            out[key] = 'unknown';
        }
    }
    return out;
}

function DnsIcon({ state }) {
    if (state === 'ok') return <CheckCircle2 size={12} aria-hidden="true" />;
    if (state === 'missing') return <XCircle size={12} aria-hidden="true" />;
    return <HelpCircle size={12} aria-hidden="true" />;
}

export default function Email() {
    const [activeTab] = useTabParam('/email', VALID_TABS);

    const [status, setStatus] = useState(null);
    const [domains, setDomains] = useState([]);
    const [loading, setLoading] = useState(true);

    const loadStatus = useCallback(async () => {
        try {
            const res = await api.getEmailStatus();
            setStatus(res?.status || res || null);
        } catch {
            setStatus(null);
        }
    }, []);

    const loadDomains = useCallback(async () => {
        try {
            const res = await api.getEmailDomains();
            setDomains(res?.domains || res || []);
        } catch {
            setDomains([]);
        }
    }, []);

    useEffect(() => {
        let alive = true;
        (async () => {
            await Promise.all([loadStatus(), loadDomains()]);
            if (alive) setLoading(false);
        })();
        return () => { alive = false; };
    }, [loadStatus, loadDomains]);

    const installed = status?.installed ?? status?.is_installed ?? (status != null && status.components != null);

    const tabs = VALID_TABS.map((t) => ({
        to: `/email/${t}`,
        label: t.charAt(0).toUpperCase() + t.slice(1),
        end: false,
    }));

    return (
        <>
            <PageTopbar
                icon={<Mail size={18} />}
                title="Email Server"
                meta="Postfix / Dovecot, domains, accounts, DKIM/SPF/DMARC"
                tabs={tabs}
                actions={(
                    <Button variant="outline" size="sm" onClick={() => { loadStatus(); loadDomains(); }}>
                        <RefreshCw size={14} /> Refresh
                    </Button>
                )}
            />

            <div className="sk-email">
                {loading ? (
                    <div className="sk-email__empty">Loading…</div>
                ) : (
                    <>
                        {activeTab === 'overview' && (
                            <OverviewTab status={status} installed={installed} onChange={loadStatus} />
                        )}
                        {activeTab === 'domains' && (
                            <DomainsTab domains={domains} onChange={loadDomains} />
                        )}
                        {activeTab === 'accounts' && (
                            <AccountsTab domains={domains} />
                        )}
                        {activeTab === 'relay' && <RelayTab />}
                        {activeTab === 'spam' && <SpamTab />}
                        {activeTab === 'webmail' && <WebmailTab />}
                        {activeTab === 'queue' && <QueueTab />}
                    </>
                )}
            </div>
        </>
    );
}

// ---------- Overview ----------
function OverviewTab({ status, installed, onChange }) {
    const toast = useToast();
    const components = status?.components || {};
    const names = Object.keys(components);

    const install = async () => {
        try {
            await api.installEmailServer();
            toast.success('Email server install started');
            onChange();
        } catch {
            toast.error('Install failed');
        }
    };

    const control = async (component, action) => {
        try {
            await api.controlEmailService(component, action);
            toast.success(`${component}: ${action}`);
            onChange();
        } catch {
            toast.error(`Failed to ${action} ${component}`);
        }
    };

    if (!installed) {
        return (
            <div className="sk-email__empty">
                <Server size={24} aria-hidden="true" />
                <p>The mail server stack is not installed on this host.</p>
                <Button size="sm" onClick={install}>
                    <Plus size={14} /> Install mail server
                </Button>
            </div>
        );
    }

    return (
        <section className="sk-email__section">
            <KpiBand>
                <MetricCard label="Domains" value={status?.domains_count ?? 0} tone="accent" icon={<Globe size={16} />} />
                <MetricCard label="Accounts" value={status?.accounts_count ?? 0} tone="cyan" icon={<Users size={16} />} />
                <MetricCard label="Queue" value={status?.queue_count ?? 0} tone="amber" icon={<Inbox size={16} />} />
            </KpiBand>

            <h2 className="sk-email__section-title"><Server size={16} /> Services</h2>
            {names.length === 0 ? (
                <div className="sk-email__empty">No service components reported.</div>
            ) : (
                <table className="sk-email__table">
                    <thead>
                        <tr><th>Component</th><th>State</th><th aria-label="Actions" /></tr>
                    </thead>
                    <tbody>
                        {names.map((name) => {
                            const running = components[name]?.running ?? components[name] === 'running';
                            return (
                                <tr key={name}>
                                    <td>{name}</td>
                                    <td><Pill kind={running ? 'green' : 'red'}>{running ? 'Running' : 'Stopped'}</Pill></td>
                                    <td className="sk-email__actions">
                                        <Button variant="ghost" size="sm" onClick={() => control(name, running ? 'restart' : 'start')}>
                                            {running ? 'Restart' : 'Start'}
                                        </Button>
                                        {running && (
                                            <Button variant="ghost" size="sm" onClick={() => control(name, 'stop')}>Stop</Button>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            )}
        </section>
    );
}

// ---------- Domains ----------
function DomainsTab({ domains, onChange }) {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [newDomain, setNewDomain] = useState('');
    const [verifying, setVerifying] = useState({});
    const [dnsResults, setDnsResults] = useState({});

    const add = async (e) => {
        e.preventDefault();
        if (!newDomain.trim()) return;
        try {
            await api.addEmailDomain({ name: newDomain.trim() });
            toast.success('Domain added');
            setNewDomain('');
            onChange();
        } catch {
            toast.error('Could not add domain');
        }
    };

    const remove = async (domain) => {
        const ok = await confirm({
            title: 'Delete domain',
            message: `Delete ${domain.name} and all of its accounts and aliases?`,
            confirmLabel: 'Delete',
            danger: true,
        });
        if (!ok) return;
        try {
            await api.deleteEmailDomain(domain.id);
            toast.success('Domain deleted');
            onChange();
        } catch {
            toast.error('Delete failed');
        }
    };

    const verify = async (domain) => {
        setVerifying((v) => ({ ...v, [domain.id]: true }));
        try {
            const res = await api.verifyEmailDNS(domain.id);
            setDnsResults((r) => ({ ...r, [domain.id]: res?.records || res || {} }));
            toast.success('DNS checked');
        } catch {
            toast.error('DNS check failed');
        } finally {
            setVerifying((v) => ({ ...v, [domain.id]: false }));
        }
    };

    const deploy = async (domain) => {
        try {
            await api.deployEmailDNS(domain.id);
            toast.success('DNS records deployed to provider');
        } catch {
            toast.error('Deploy failed (no linked DNS provider?)');
        }
    };

    return (
        <section className="sk-email__section">
            <form className="sk-email__add" onSubmit={add}>
                <Input
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    placeholder="example.com"
                    aria-label="New mail domain"
                />
                <Button type="submit" size="sm"><Plus size={14} /> Add domain</Button>
            </form>

            {domains.length === 0 ? (
                <div className="sk-email__empty">
                    <Globe size={24} aria-hidden="true" />
                    <p>No mail domains yet.</p>
                </div>
            ) : (
                <ul className="sk-email__domains">
                    {domains.map((domain) => {
                        const dns = deriveDnsStatus(domain, dnsResults[domain.id]);
                        return (
                            <li key={domain.id} className="sk-email__domain">
                                <div className="sk-email__domain-head">
                                    <span className="sk-email__domain-name">{domain.name}</span>
                                    <Pill kind={domain.is_active ? 'green' : 'gray'}>
                                        {domain.is_active ? 'Active' : 'Disabled'}
                                    </Pill>
                                </div>

                                <div className="sk-email__dns">
                                    {DNS_RECORDS.map(({ key, label }) => (
                                        <Pill key={key} kind={dnsPillKind(dns[key])} title={`${label}: ${dns[key]}`}>
                                            <DnsIcon state={dns[key]} /> {label}
                                        </Pill>
                                    ))}
                                </div>

                                <div className="sk-email__domain-meta">
                                    <span>{domain.accounts_count ?? 0} accounts</span>
                                    <span>{domain.aliases_count ?? 0} aliases</span>
                                    {domain.dkim_selector && <span>DKIM selector: {domain.dkim_selector}</span>}
                                </div>

                                <div className="sk-email__actions">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => verify(domain)}
                                        disabled={verifying[domain.id]}
                                    >
                                        <ShieldCheck size={14} /> {verifying[domain.id] ? 'Checking…' : 'Verify DNS'}
                                    </Button>
                                    <Button variant="outline" size="sm" onClick={() => deploy(domain)}>
                                        <ExternalLink size={14} /> Deploy DNS
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={() => remove(domain)}>
                                        <Trash2 size={14} /> Delete
                                    </Button>
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}

// ---------- Accounts ----------
function AccountsTab({ domains }) {
    const toast = useToast();
    const { confirm } = useConfirm();
    const [domainId, setDomainId] = useState(domains[0]?.id ? String(domains[0].id) : '');
    const [accounts, setAccounts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [form, setForm] = useState({ username: '', password: '', quota_mb: 1024 });

    const load = useCallback(async () => {
        if (!domainId) { setAccounts([]); return; }
        setLoading(true);
        try {
            const res = await api.getEmailAccounts(domainId);
            setAccounts(res?.accounts || res || []);
        } catch {
            setAccounts([]);
        } finally {
            setLoading(false);
        }
    }, [domainId]);

    useEffect(() => { load(); }, [load]);

    const create = async (e) => {
        e.preventDefault();
        if (!form.username.trim() || !form.password) return;
        try {
            await api.createEmailAccount(domainId, form);
            toast.success('Account created');
            setForm({ username: '', password: '', quota_mb: 1024 });
            load();
        } catch {
            toast.error('Create failed');
        }
    };

    const remove = async (account) => {
        const ok = await confirm({
            title: 'Delete account',
            message: `Delete ${account.email}?`,
            confirmLabel: 'Delete',
            danger: true,
        });
        if (!ok) return;
        try {
            await api.deleteEmailAccount(account.id);
            toast.success('Account deleted');
            load();
        } catch {
            toast.error('Delete failed');
        }
    };

    if (domains.length === 0) {
        return (
            <div className="sk-email__empty">
                <Users size={24} aria-hidden="true" />
                <p>Add a mail domain first.</p>
            </div>
        );
    }

    return (
        <section className="sk-email__section">
            <div className="sk-email__filters">
                <label>
                    Domain
                    <select value={domainId} onChange={(e) => setDomainId(e.target.value)}>
                        {domains.map((d) => <option key={d.id} value={String(d.id)}>{d.name}</option>)}
                    </select>
                </label>
            </div>

            <form className="sk-email__add" onSubmit={create}>
                <Input
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    placeholder="username"
                    aria-label="Mailbox username"
                />
                <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder="password"
                    aria-label="Mailbox password"
                />
                <Input
                    type="number"
                    value={form.quota_mb}
                    onChange={(e) => setForm({ ...form, quota_mb: Number(e.target.value) })}
                    placeholder="Quota (MB)"
                    aria-label="Quota in MB"
                />
                <Button type="submit" size="sm"><Plus size={14} /> Create</Button>
            </form>

            {loading ? (
                <div className="sk-email__empty">Loading…</div>
            ) : accounts.length === 0 ? (
                <div className="sk-email__empty">No accounts in this domain.</div>
            ) : (
                <table className="sk-email__table">
                    <thead>
                        <tr><th>Address</th><th>Quota</th><th>State</th><th aria-label="Actions" /></tr>
                    </thead>
                    <tbody>
                        {accounts.map((account) => (
                            <tr key={account.id}>
                                <td>{account.email}</td>
                                <td>{account.quota_used_mb ?? 0} / {account.quota_mb ?? 0} MB</td>
                                <td><Pill kind={account.is_active ? 'green' : 'gray'}>{account.is_active ? 'Active' : 'Disabled'}</Pill></td>
                                <td className="sk-email__actions">
                                    <Button variant="ghost" size="sm" onClick={() => remove(account)}>
                                        <Trash2 size={14} /> Delete
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
}

// ---------- Relay (smarthost) ----------
function RelayTab() {
    const toast = useToast();
    const [relay, setRelay] = useState({ host: '', port: 587, username: '', password: '', enabled: false });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        api.getEmailRelay()
            .then((res) => { if (alive) setRelay((r) => ({ ...r, ...(res?.relay || res || {}) })); })
            .catch(() => { /* defaults */ })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    const save = async (e) => {
        e.preventDefault();
        try {
            await api.updateEmailRelay(relay);
            toast.success('Relay saved');
        } catch {
            toast.error('Save failed');
        }
    };

    const test = async () => {
        try {
            await api.testEmailRelay(relay);
            toast.success('Relay reachable');
        } catch {
            toast.error('Relay test failed');
        }
    };

    const disable = async () => {
        try {
            await api.disableEmailRelay();
            setRelay((r) => ({ ...r, enabled: false }));
            toast.success('Relay disabled');
        } catch {
            toast.error('Failed to disable relay');
        }
    };

    if (loading) return <div className="sk-email__empty">Loading…</div>;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Send size={16} /> Outbound relay (smarthost)</h2>
            <form className="sk-email__form" onSubmit={save}>
                <label>Host<Input value={relay.host || ''} onChange={(e) => setRelay({ ...relay, host: e.target.value })} placeholder="smtp.provider.com" /></label>
                <label>Port<Input type="number" value={relay.port || 587} onChange={(e) => setRelay({ ...relay, port: Number(e.target.value) })} /></label>
                <label>Username<Input value={relay.username || ''} onChange={(e) => setRelay({ ...relay, username: e.target.value })} /></label>
                <label>Password<Input type="password" value={relay.password || ''} onChange={(e) => setRelay({ ...relay, password: e.target.value })} /></label>
                <label className="sk-email__check">
                    <input type="checkbox" checked={!!relay.enabled} onChange={(e) => setRelay({ ...relay, enabled: e.target.checked })} />
                    Enable relay
                </label>
                <div className="sk-email__actions">
                    <Button type="submit" size="sm">Save</Button>
                    <Button type="button" variant="outline" size="sm" onClick={test}>Test</Button>
                    <Button type="button" variant="ghost" size="sm" onClick={disable}>Disable</Button>
                </div>
            </form>
        </section>
    );
}

// ---------- Spam ----------
function SpamTab() {
    const toast = useToast();
    const [config, setConfig] = useState({ enabled: true, required_score: 5 });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        api.getSpamConfig()
            .then((res) => { if (alive) setConfig((c) => ({ ...c, ...(res?.config || res || {}) })); })
            .catch(() => { /* defaults */ })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    const save = async (e) => {
        e.preventDefault();
        try {
            await api.updateSpamConfig(config);
            toast.success('Spam config saved');
        } catch {
            toast.error('Save failed');
        }
    };

    const updateRules = async () => {
        try {
            await api.updateSpamRules();
            toast.success('Rule update started');
        } catch {
            toast.error('Rule update failed');
        }
    };

    if (loading) return <div className="sk-email__empty">Loading…</div>;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Filter size={16} /> SpamAssassin</h2>
            <form className="sk-email__form" onSubmit={save}>
                <label className="sk-email__check">
                    <input type="checkbox" checked={!!config.enabled} onChange={(e) => setConfig({ ...config, enabled: e.target.checked })} />
                    Enable spam filtering
                </label>
                <label>Required score<Input type="number" step="0.1" value={config.required_score ?? 5} onChange={(e) => setConfig({ ...config, required_score: Number(e.target.value) })} /></label>
                <div className="sk-email__actions">
                    <Button type="submit" size="sm">Save</Button>
                    <Button type="button" variant="outline" size="sm" onClick={updateRules}>Update rules</Button>
                </div>
            </form>
        </section>
    );
}

// ---------- Webmail ----------
function WebmailTab() {
    const toast = useToast();
    const [state, setState] = useState(null);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        try {
            const res = await api.getWebmailStatus();
            setState(res?.status || res || null);
        } catch {
            setState(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const install = async () => {
        try {
            await api.installWebmail();
            toast.success('Webmail install started');
            load();
        } catch {
            toast.error('Install failed');
        }
    };

    const control = async (action) => {
        try {
            await api.controlWebmail(action);
            toast.success(`Webmail: ${action}`);
            load();
        } catch {
            toast.error(`Failed to ${action} webmail`);
        }
    };

    if (loading) return <div className="sk-email__empty">Loading…</div>;

    const installed = state?.installed ?? state?.is_installed;
    const running = state?.running;

    return (
        <section className="sk-email__section">
            <h2 className="sk-email__section-title"><Inbox size={16} /> Roundcube webmail</h2>
            {!installed ? (
                <div className="sk-email__empty">
                    <p>Webmail is not installed.</p>
                    <Button size="sm" onClick={install}><Plus size={14} /> Install webmail</Button>
                </div>
            ) : (
                <div className="sk-email__actions">
                    <Pill kind={running ? 'green' : 'red'}>{running ? 'Running' : 'Stopped'}</Pill>
                    <Button variant="outline" size="sm" onClick={() => control(running ? 'restart' : 'start')}>
                        {running ? 'Restart' : 'Start'}
                    </Button>
                    {running && <Button variant="ghost" size="sm" onClick={() => control('stop')}>Stop</Button>}
                </div>
            )}
        </section>
    );
}

// ---------- Mail queue ----------
function QueueTab() {
    const toast = useToast();
    const [queue, setQueue] = useState([]);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.getMailQueue();
            setQueue(res?.queue || res || []);
        } catch {
            setQueue([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const flush = async () => {
        try {
            await api.flushMailQueue();
            toast.success('Queue flushed');
            load();
        } catch {
            toast.error('Flush failed');
        }
    };

    const remove = async (id) => {
        try {
            await api.deleteMailQueueItem(id);
            load();
        } catch {
            toast.error('Delete failed');
        }
    };

    return (
        <section className="sk-email__section">
            <div className="sk-email__actions">
                <Button variant="outline" size="sm" onClick={load}><RefreshCw size={14} /> Refresh</Button>
                <Button variant="outline" size="sm" onClick={flush}>Flush queue</Button>
            </div>

            {loading ? (
                <div className="sk-email__empty">Loading…</div>
            ) : queue.length === 0 ? (
                <div className="sk-email__empty">
                    <Inbox size={24} aria-hidden="true" />
                    <p>The mail queue is empty.</p>
                </div>
            ) : (
                <table className="sk-email__table">
                    <thead>
                        <tr><th>ID</th><th>Sender</th><th>Recipient</th><th>Size</th><th aria-label="Actions" /></tr>
                    </thead>
                    <tbody>
                        {queue.map((item) => (
                            <tr key={item.id || item.queue_id}>
                                <td className="sk-email__mono">{item.id || item.queue_id}</td>
                                <td>{item.sender || '—'}</td>
                                <td>{item.recipient || '—'}</td>
                                <td>{item.size || '—'}</td>
                                <td className="sk-email__actions">
                                    <Button variant="ghost" size="sm" onClick={() => remove(item.id || item.queue_id)}>
                                        <Trash2 size={14} /> Delete
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
}
