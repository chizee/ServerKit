import React, { useState, useEffect } from 'react';
import api from '../../services/api';
import ConfirmDialog from '../ConfirmDialog';
import { useToast } from '../../contexts/ToastContext';
import Modal from '../Modal';
import { InfoList, InfoItem } from '../InfoList';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';

const Fail2banTab = () => {
    const [status, setStatus] = useState(null);
    const [bans, setBans] = useState([]);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [showBanModal, setShowBanModal] = useState(false);
    const [banIP, setBanIP] = useState('');
    const [banJail, setBanJail] = useState('sshd');
    const [confirmDialog, setConfirmDialog] = useState(null);
    const toast = useToast();

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [statusData, bansData] = await Promise.all([
                api.getFail2banStatus(),
                api.getAllFail2banBans().catch(() => ({ banned_ips: [] }))
            ]);
            setStatus(statusData);
            setBans(bansData.banned_ips || []);
        } catch (error) {
            console.error('Failed to load Fail2ban data:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleInstall = async () => {
        setActionLoading(true);
        try {
            await api.installFail2ban();
            toast.success('Fail2ban installed successfully');
            await loadData();
        } catch (error) {
            toast.error(`Failed to install: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleBan = async () => {
        if (!banIP.trim()) return;
        setActionLoading(true);
        try {
            await api.fail2banBan(banIP, banJail);
            toast.success(`IP ${banIP} banned in ${banJail}`);
            setShowBanModal(false);
            setBanIP('');
            await loadData();
        } catch (error) {
            toast.error(`Failed to ban IP: ${error.message}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleUnban = async (ip, jail) => {
        setConfirmDialog({
            title: 'Unban IP',
            message: `Are you sure you want to unban ${ip} from ${jail}?`,
            confirmText: 'Unban',
            variant: 'warning',
            onConfirm: async () => {
                try {
                    await api.fail2banUnban(ip, jail);
                    toast.success(`IP ${ip} unbanned`);
                    await loadData();
                } catch (error) {
                    toast.error(`Failed to unban: ${error.message}`);
                }
                setConfirmDialog(null);
            },
            onCancel: () => setConfirmDialog(null)
        });
    };

    if (loading) {
        return <div className="loading-sm">Loading Fail2ban status...</div>;
    }

    return (
        <div className="fail2ban-tab">
            {!status?.installed ? (
                <div className="empty-state">
                    <svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" fill="none" strokeWidth="1">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                    <h3>Fail2ban Not Installed</h3>
                    <p>Install Fail2ban to protect against brute force attacks.</p>
                    <Button variant="default" onClick={handleInstall} disabled={actionLoading}>
                        {actionLoading ? 'Installing...' : 'Install Fail2ban'}
                    </Button>
                </div>
            ) : (
                <>
                    <div className="card">
                        <div className="card-header">
                            <h3>Fail2ban Status</h3>
                            <div className="card-actions">
                                <Button variant="default" size="sm" onClick={() => setShowBanModal(true)}>
                                    Ban IP
                                </Button>
                                <Button variant="outline" size="sm" onClick={loadData}>
                                    Refresh
                                </Button>
                            </div>
                        </div>
                        <div className="card-body">
                            <InfoList>
                                <InfoItem label="Service">
                                    <Badge variant={status.service_running ? 'success' : 'destructive'}>
                                        {status.service_running ? 'Running' : 'Stopped'}
                                    </Badge>
                                </InfoItem>
                                <InfoItem label="Version" value={status.version || 'Unknown'} />
                                <InfoItem label="Active Jails" value={status.jails?.join(', ') || 'None'} />
                                <InfoItem label="Total Banned IPs" value={bans.length} />
                            </InfoList>
                        </div>
                    </div>

                    <div className="card">
                        <div className="card-header">
                            <h3>Banned IPs</h3>
                        </div>
                        <div className="card-body">
                            {bans.length === 0 ? (
                                <p className="text-muted">No IPs are currently banned.</p>
                            ) : (
                                <table className="table">
                                    <thead>
                                        <tr>
                                            <th>IP Address</th>
                                            <th>Jail</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {bans.map((ban, index) => (
                                            <tr key={index}>
                                                <td><code>{ban.ip}</code></td>
                                                <td><Badge variant="info">{ban.jail}</Badge></td>
                                                <td>
                                                    <Button variant="secondary" size="sm" onClick={() => handleUnban(ban.ip, ban.jail)}>
                                                        Unban
                                                    </Button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </div>
                </>
            )}

            <Modal open={showBanModal} onClose={() => setShowBanModal(false)} title="Ban IP Address">
                <div className="form-group">
                    <Label>IP Address</Label>
                    <Input
                        type="text"
                        value={banIP}
                        onChange={(e) => setBanIP(e.target.value)}
                        placeholder="192.168.1.100"
                    />
                </div>
                <div className="form-group">
                    <Label>Jail</Label>
                    <Select value={banJail} onValueChange={setBanJail}>
                        <SelectTrigger>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {status?.jails?.map(jail => (
                                <SelectItem key={jail} value={jail}>{jail}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="modal-footer">
                    <Button variant="outline" onClick={() => setShowBanModal(false)}>Cancel</Button>
                    <Button variant="destructive" onClick={handleBan} disabled={actionLoading || !banIP.trim()}>
                        {actionLoading ? 'Banning...' : 'Ban IP'}
                    </Button>
                </div>
            </Modal>

            {confirmDialog && (
                <ConfirmDialog
                    title={confirmDialog.title}
                    message={confirmDialog.message}
                    confirmText={confirmDialog.confirmText}
                    variant={confirmDialog.variant}
                    onConfirm={confirmDialog.onConfirm}
                    onCancel={confirmDialog.onCancel}
                />
            )}
        </div>
    );
};

export default Fail2banTab;
