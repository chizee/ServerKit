import { useState } from 'react';
import { DownloadCloud, FileArchive, FolderOpen, Globe2, PlugZap } from 'lucide-react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import Modal from '@/components/Modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const INSTALL_SOURCES = [
    { id: 'url', label: 'URL', icon: Globe2 },
    { id: 'path', label: 'Folder', icon: FolderOpen },
    { id: 'upload', label: 'Zip', icon: FileArchive },
];

const SourceInput = ({
    description,
    placeholder,
    value,
    onChange,
    onInstall,
    disabled,
    installDisabled,
}) => (
    <div className="plugin-install-source">
        <p className="text-muted">{description}</p>
        <div className="plugin-install-row">
            <Input
                placeholder={placeholder}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && onInstall()}
                disabled={disabled}
            />
            <Button onClick={onInstall} disabled={installDisabled}>
                <DownloadCloud aria-hidden="true" />
                {disabled ? 'Installing...' : 'Install'}
            </Button>
        </div>
    </div>
);

// Manual extension install (URL / host folder / zip upload). An occasional
// operator action, so it lives in a modal off the topbar rather than a tab.
const ManualInstallModal = ({ defaultSource = 'url', onClose, onInstalled }) => {
    const toast = useToast();
    const [installSource, setInstallSource] = useState(defaultSource);
    const [pluginUrl, setPluginUrl] = useState('');
    const [pluginPath, setPluginPath] = useState('');
    const [pluginFile, setPluginFile] = useState(null);
    const [installing, setInstalling] = useState(false);

    const handleInstall = async () => {
        let action;
        if (installSource === 'url') {
            if (!pluginUrl.trim()) return;
            action = () => api.installPlugin(pluginUrl.trim());
        } else if (installSource === 'path') {
            if (!pluginPath.trim()) return;
            action = () => api.installPluginFromPath(pluginPath.trim());
        } else if (installSource === 'upload') {
            if (!pluginFile) return;
            action = () => api.installPluginFromZip(pluginFile);
        } else {
            return;
        }

        setInstalling(true);
        try {
            const result = await action();
            toast.success(`Extension "${result.display_name}" installed. Restart backend to activate routes.`);
            onInstalled();
        } catch (err) {
            toast.error(err.message || 'Extension installation failed');
        } finally {
            setInstalling(false);
        }
    };

    return (
        <Modal open onClose={onClose} title="Install extension manually" size="md">
            <div className="plugin-install-form">
                <div className="plugin-install-form__heading">
                    <div className="plugin-install-form__icon">
                        <PlugZap aria-hidden="true" />
                    </div>
                    <div>
                        <h3>Extension source</h3>
                        <p className="text-muted">Load extension packages from a repository, host folder, or zip archive.</p>
                    </div>
                </div>

                <div className="plugin-install-tabs" role="tablist" aria-label="Extension install source">
                    {INSTALL_SOURCES.map((source) => {
                        const SourceIcon = source.icon;
                        return (
                            <button
                                key={source.id}
                                role="tab"
                                type="button"
                                aria-selected={installSource === source.id}
                                className={`plugin-install-tab ${installSource === source.id ? 'plugin-install-tab--active' : ''}`}
                                onClick={() => setInstallSource(source.id)}
                            >
                                <SourceIcon aria-hidden="true" />
                                {source.label}
                            </button>
                        );
                    })}
                </div>

                {installSource === 'url' && (
                    <SourceInput
                        description="Paste a GitHub repo URL, release URL, or direct zip link."
                        placeholder="https://github.com/user/serverkit-plugin"
                        value={pluginUrl}
                        onChange={setPluginUrl}
                        onInstall={handleInstall}
                        disabled={installing}
                        installDisabled={installing || !pluginUrl.trim()}
                    />
                )}

                {installSource === 'path' && (
                    <SourceInput
                        description="Use an absolute path that exists on the backend host or inside the backend container."
                        placeholder="/opt/serverkit/plugins/my-plugin"
                        value={pluginPath}
                        onChange={setPluginPath}
                        onInstall={handleInstall}
                        disabled={installing}
                        installDisabled={installing || !pluginPath.trim()}
                    />
                )}

                {installSource === 'upload' && (
                    <div className="plugin-install-source">
                        <p className="text-muted">
                            Upload an extension zip with <code>plugin.json</code> at the top level or one folder deep.
                        </p>
                        <div className="plugin-install-row">
                            <Input
                                type="file"
                                className="marketplace-file-input"
                                accept=".zip,application/zip,application/x-zip-compressed"
                                disabled={installing}
                                onChange={(event) => setPluginFile(event.target.files?.[0] || null)}
                            />
                            <Button
                                onClick={handleInstall}
                                disabled={installing || !pluginFile}
                            >
                                <DownloadCloud aria-hidden="true" />
                                {installing ? 'Installing...' : 'Install'}
                            </Button>
                        </div>
                        {pluginFile && (
                            <div className="plugin-file-note">
                                {pluginFile.name} | {(pluginFile.size / 1024).toFixed(1)} KB
                            </div>
                        )}
                    </div>
                )}
            </div>
        </Modal>
    );
};

export default ManualInstallModal;
