import { useState } from 'react';
import { Copy, Check, AlertTriangle } from 'lucide-react';
import Modal from '../Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';

const SCOPE_OPTIONS = [
    { value: '*', label: 'Full Access' },
    { value: 'apps:read', label: 'Apps (Read)' },
    { value: 'apps:write', label: 'Apps (Write)' },
    { value: 'docker:read', label: 'Docker (Read)' },
    { value: 'docker:write', label: 'Docker (Write)' },
    { value: 'system:read', label: 'System (Read)' },
    { value: 'databases:read', label: 'Databases (Read)' },
    { value: 'databases:write', label: 'Databases (Write)' },
    { value: 'backups:read', label: 'Backups (Read)' },
    { value: 'backups:write', label: 'Backups (Write)' },
    { value: 'domains:read', label: 'Domains (Read)' },
    { value: 'domains:write', label: 'Domains (Write)' },
];

const TIER_OPTIONS = [
    { value: 'standard', label: 'Standard', desc: '100 req/min' },
    { value: 'elevated', label: 'Elevated', desc: '500 req/min' },
    { value: 'unlimited', label: 'Unlimited', desc: '5000 req/min' },
];

const ApiKeyModal = ({ onClose, onSubmit, createdKey }) => {
    const [name, setName] = useState('');
    const [scopes, setScopes] = useState(['*']);
    const [tier, setTier] = useState('standard');
    const [expiresAt, setExpiresAt] = useState('');
    const [saving, setSaving] = useState(false);
    const [copied, setCopied] = useState(false);

    const handleScopeToggle = (scope) => {
        if (scope === '*') {
            setScopes(['*']);
            return;
        }
        setScopes(prev => {
            const filtered = prev.filter(s => s !== '*');
            if (filtered.includes(scope)) {
                return filtered.filter(s => s !== scope);
            }
            return [...filtered, scope];
        });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        setSaving(true);
        try {
            await onSubmit({
                name: name.trim(),
                scopes,
                tier,
                expires_at: expiresAt || null,
            });
        } finally {
            setSaving(false);
        }
    };

    const copyKey = () => {
        if (createdKey) {
            navigator.clipboard.writeText(createdKey);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    // Show created key view
    if (createdKey) {
        return (
            <Modal open={true} onClose={onClose} title="API Key Created" className="api-key-modal">
                        <div className="api-key-modal__warning">
                            <AlertTriangle size={16} />
                            <span>Copy this key now. It will not be shown again.</span>
                        </div>
                        <div className="api-key-modal__key-display">
                            <code>{createdKey}</code>
                            <Button variant="outline" size="sm" onClick={copyKey}>
                                {copied ? <Check size={14} /> : <Copy size={14} />}
                                {copied ? 'Copied' : 'Copy'}
                            </Button>
                        </div>
                    <div className="modal-footer">
                        <Button variant="default" onClick={onClose}>Done</Button>
                    </div>
            </Modal>
        );
    }

    return (
        <Modal open={true} onClose={onClose} title="Create API Key" className="api-key-modal">
                <form onSubmit={handleSubmit}>
                    <div className="modal-body">
                        <div className="form-group">
                            <Label>Name</Label>
                            <Input
                                type="text"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="e.g. CI/CD Pipeline, Monitoring Script"
                                required
                            />
                        </div>

                        <div className="form-group">
                            <Label>Tier</Label>
                            <div className="api-key-modal__tiers">
                                {TIER_OPTIONS.map(t => (
                                    <button
                                        key={t.value}
                                        type="button"
                                        className={`api-key-modal__tier-btn ${tier === t.value ? 'active' : ''}`}
                                        onClick={() => setTier(t.value)}
                                    >
                                        <span className="api-key-modal__tier-label">{t.label}</span>
                                        <span className="api-key-modal__tier-desc">{t.desc}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="form-group">
                            <Label>Scopes</Label>
                            <div className="api-key-modal__scopes">
                                {SCOPE_OPTIONS.map(s => (
                                    <label key={s.value} className="api-key-modal__scope-item">
                                        <Checkbox
                                            checked={scopes.includes(s.value) || (s.value !== '*' && scopes.includes('*'))}
                                            disabled={s.value !== '*' && scopes.includes('*')}
                                            onCheckedChange={() => handleScopeToggle(s.value)}
                                        />
                                        <span>{s.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div className="form-group">
                            <Label>Expiration (optional)</Label>
                            <Input
                                type="datetime-local"
                                value={expiresAt}
                                onChange={e => setExpiresAt(e.target.value)}
                            />
                            <span className="form-help">Leave empty for no expiration</span>
                        </div>
                    </div>
                    <div className="modal-footer">
                        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                        <Button type="submit" variant="default" disabled={saving || !name.trim()}>
                            {saving ? 'Creating...' : 'Create Key'}
                        </Button>
                    </div>
                </form>
        </Modal>
    );
};

export default ApiKeyModal;
