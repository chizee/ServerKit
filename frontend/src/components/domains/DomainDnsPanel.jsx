// The DNS records section shown inside the Domains drawer — the same inline
// experience for an app-created domain and a Cloudflare zone, so the two no longer
// feel like different products. For a Cloudflare domain it shows the *live* zone
// records (tagged ServerKit-managed vs your own), so you can see the real DNS
// without leaving the drawer; for a ServerKit/manual zone it shows the managed
// records. Admins can add a record inline (the zone is adopted on demand), and
// deeper management links out to the Cloudflare ops surface / full DNS page.
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Plus, RefreshCw, ExternalLink, Cloud, ShieldCheck } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { ProviderBrandIcon } from '../icons/ProviderBrands';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { FormField, FormRow } from '../FormField';
import {
    Select, SelectTrigger, SelectContent, SelectItem, SelectValue,
} from '@/components/ui/select';

const RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'CAA', 'NS'];
const PROXYABLE = ['A', 'AAAA', 'CNAME'];
const EMPTY_FORM = { record_type: 'A', name: '@', content: '', ttl: 3600, priority: '', proxied: false };

const normalizeLive = (r) => ({
    id: r.id, type: r.type, name: r.name, content: r.content,
    ttl: r.ttl, proxied: r.proxied, priority: r.priority, source: r.managed_by,
});
const normalizeManaged = (r) => ({
    id: r.id, type: r.record_type, name: r.name, content: r.content,
    ttl: r.ttl, proxied: r.proxied, priority: r.priority, source: 'serverkit',
});

export default function DomainDnsPanel({ domain, isAdmin }) {
    const navigate = useNavigate();
    const toast = useToast();
    const isCloudflare = domain?.provider === 'cloudflare';
    const canLive = isCloudflare && !!domain?.provider_zone_id && !!domain?.config_id;

    const [records, setRecords] = useState([]);
    const [state, setState] = useState('loading'); // loading | ready | none | error
    const [error, setError] = useState('');
    const [zoneId, setZoneId] = useState(domain?.zone_id || null); // local DNSZone id, once known
    const [showAdd, setShowAdd] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);

    const load = useCallback(async () => {
        if (!domain) return;
        setState('loading');
        setError('');
        setZoneId(domain.zone_id || null); // reset so a prior domain's id can't leak in
        try {
            if (canLive) {
                const res = await api.getProviderRecords(domain.config_id, domain.provider_zone_id);
                if (!res.success) { setError(res.error || 'Could not load records'); setState('error'); return; }
                setRecords((res.records || []).map(normalizeLive));
                setZoneId(domain.zone_id || null);
            } else if (domain.zone_id) {
                const res = await api.getDNSRecords(domain.zone_id);
                setRecords((res.records || []).map(normalizeManaged));
                setZoneId(domain.zone_id);
            } else {
                // App/manual domain without a provider zone — match a local zone by name.
                const zones = (await api.getDNSZones()).zones || [];
                const zone = zones.find((z) => z.domain === domain.name);
                if (!zone) { setState('none'); return; }
                const res = await api.getDNSRecords(zone.id);
                setRecords((res.records || []).map(normalizeManaged));
                setZoneId(zone.id);
            }
            setState('ready');
        } catch (e) {
            setError(e.message || 'Could not load records');
            setState('error');
        }
    }, [domain, canLive]);

    useEffect(() => { setShowAdd(false); setForm(EMPTY_FORM); load(); }, [load]);

    // Materialize the local zone row on demand (writes / Cloudflare ops need it).
    async function ensureZone() {
        if (zoneId) return zoneId;
        const zone = await api.adoptDnsZone(domain.name, domain.config_id);
        setZoneId(zone.id);
        return zone.id;
    }

    async function handleAdd() {
        setSaving(true);
        try {
            const zid = await ensureZone();
            await api.createDNSRecord(zid, {
                record_type: form.record_type,
                name: form.name || '@',
                content: form.content,
                ttl: Number(form.ttl) || 3600,
                priority: form.priority !== '' && form.priority != null ? Number(form.priority) : null,
                proxied: isCloudflare && PROXYABLE.includes(form.record_type) ? !!form.proxied : false,
            });
            toast.success('Record added');
            setShowAdd(false);
            setForm(EMPTY_FORM);
            await load();
        } catch (e) {
            toast.error(e.message || 'Failed to add record');
        } finally {
            setSaving(false);
        }
    }

    async function openCloudflareOps() {
        try {
            const zid = await ensureZone();
            navigate(`/cloudflare/zones/${zid}`);
        } catch (e) {
            toast.error(e.message || 'Could not open Cloudflare');
        }
    }

    // A proxied A/AAAA/CNAME means Cloudflare terminates TLS at its edge — i.e. the
    // site is served over HTTPS with no separate certificate to manage here.
    const hasProxiedSSL = isCloudflare && records.some((r) => r.proxied && PROXYABLE.includes(r.type));

    return (
        <div className="ddp">
            <div className="ddp__head">
                <h3 className="ddp__title">
                    DNS records{state === 'ready' && <span className="ddp__count"> · {records.length}</span>}
                </h3>
                <div className="ddp__head-actions">
                    <Button variant="ghost" size="sm" onClick={load} title="Refresh records">
                        <RefreshCw size={14} />
                    </Button>
                    {isAdmin && (state === 'ready' || state === 'none') && (
                        <Button size="sm" onClick={() => setShowAdd((v) => !v)}>
                            <Plus size={14} /> Add record
                        </Button>
                    )}
                </div>
            </div>

            {canLive && (
                <p className="ddp__hint">
                    Live from Cloudflare — records ServerKit manages are tagged; the rest are your own and shown read-only.
                </p>
            )}

            {state === 'ready' && hasProxiedSSL && (
                <p className="ddp__ssl">
                    <ShieldCheck size={13} /> HTTPS is served by Cloudflare on proxied records — no separate certificate needed.
                </p>
            )}

            {showAdd && isAdmin && (
                <div className="ddp__form">
                    <FormRow>
                        <FormField label="Type">
                            <Select value={form.record_type} onValueChange={(v) => setForm({ ...form, record_type: v })}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>{RECORD_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                            </Select>
                        </FormField>
                        <FormField label="Name">
                            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="@ or subdomain" />
                        </FormField>
                    </FormRow>
                    <FormField label="Content">
                        <Input value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="IP address or target" />
                    </FormField>
                    <FormRow>
                        <FormField label="TTL">
                            <Input type="number" value={form.ttl} onChange={(e) => setForm({ ...form, ttl: e.target.value })} />
                        </FormField>
                        {(form.record_type === 'MX' || form.record_type === 'SRV') && (
                            <FormField label="Priority">
                                <Input type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} />
                            </FormField>
                        )}
                    </FormRow>
                    {isCloudflare && PROXYABLE.includes(form.record_type) && (
                        <label className="ddp__proxy-toggle">
                            <input type="checkbox" checked={!!form.proxied} onChange={(e) => setForm({ ...form, proxied: e.target.checked })} />
                            Proxy through Cloudflare (orange cloud)
                        </label>
                    )}
                    <div className="ddp__form-actions">
                        <Button variant="outline" size="sm" onClick={() => setShowAdd(false)}>Cancel</Button>
                        <Button size="sm" disabled={!form.content || saving} onClick={handleAdd}>
                            {saving ? 'Adding…' : 'Add record'}
                        </Button>
                    </div>
                </div>
            )}

            {state === 'loading' && <p className="ddp__msg">Loading records…</p>}
            {state === 'error' && <p className="ddp__msg ddp__msg--error">{error}</p>}
            {state === 'none' && <p className="ddp__msg">This domain isn&apos;t set up for DNS in ServerKit yet.</p>}

            {state === 'ready' && (
                records.length === 0 ? (
                    <p className="ddp__msg">No DNS records yet.</p>
                ) : (
                    <div className="ddp__table-wrap">
                        <table className="sk-dtable ddp__table">
                            <thead>
                                <tr>
                                    <th className="ddp__c-type">Type</th>
                                    <th className="ddp__c-name">Name</th>
                                    <th>Content</th>
                                    <th className="ddp__c-ttl">TTL</th>
                                    {isCloudflare && <th className="ddp__c-proxy">Proxy</th>}
                                    {canLive && <th className="ddp__c-src">Source</th>}
                                </tr>
                            </thead>
                            <tbody>
                                {records.map((r) => (
                                    <tr key={r.id}>
                                        <td><span className={`dns-rtype dns-rtype--${(r.type || '').toLowerCase()}`}>{r.type}</span></td>
                                        <td className="sk-cell-mono ddp__c-name" title={r.name}>{r.name}</td>
                                        <td className="sk-cell-mono ddp__content" title={r.content}>{r.priority ? `${r.priority} ` : ''}{r.content}</td>
                                        <td className="sk-cell-mono">{r.ttl === 1 ? 'Auto' : r.ttl}</td>
                                        {isCloudflare && (
                                            <td>{r.proxied
                                                ? <span className="ddp__proxy ddp__proxy--on"><Cloud size={12} /> Proxied</span>
                                                : <span className="ddp__proxy">DNS only</span>}</td>
                                        )}
                                        {canLive && (
                                            <td>{r.source === 'serverkit'
                                                ? <span className="ddp__src ddp__src--sk">ServerKit</span>
                                                : <span className="ddp__src">External</span>}</td>
                                        )}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )
            )}

            <div className="ddp__foot">
                {isCloudflare && (
                    <Button variant="outline" size="sm" onClick={openCloudflareOps}>
                        <ProviderBrandIcon provider="cloudflare" size={14} /> Open in Cloudflare
                    </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => navigate('/dns')}>
                    <Network size={14} /> Full DNS page <ExternalLink size={12} />
                </Button>
            </div>
        </div>
    );
}
