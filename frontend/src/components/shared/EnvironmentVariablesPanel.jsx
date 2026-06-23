import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';

/**
 * Read-mostly facade showing the *resolved* shared variables for a resource —
 * i.e. the merged effective set from every shared variable group attached to it.
 * Secret values arrive pre-masked from the backend; this panel never reveals
 * them. Editing happens in SharedVariableGroups (the group is the source of
 * truth); this surface is the read-side facade meant to be embedded on a
 * resource's detail page.
 *
 * Props:
 *   resourceType  one of SharedResourceService.RESOURCE_TYPES
 *   resourceId    the resource's id (number or string)
 */
const EnvironmentVariablesPanel = ({ resourceType, resourceId }) => {
    const toast = useToast();
    const [variables, setVariables] = useState([]);
    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('');

    const load = useCallback(async () => {
        if (!resourceType || resourceId == null) return;
        try {
            setLoading(true);
            const data = await api.getResolvedVariables(resourceType, resourceId);
            setVariables(data.variables || []);
            setGroups(data.groups || []);
        } catch (err) {
            toast.error('Failed to load shared variables');
            console.error('Failed to load resolved variables:', err);
        } finally {
            setLoading(false);
        }
    }, [resourceType, resourceId, toast]);

    useEffect(() => { load(); }, [load]);

    const filtered = filter
        ? variables.filter((v) => v.key.toLowerCase().includes(filter.toLowerCase()))
        : variables;

    if (loading) {
        return <div className="shared-vars-panel shared-vars-panel--loading">Loading shared variables…</div>;
    }

    return (
        <div className="shared-vars-panel">
            <div className="shared-vars-panel__header">
                <h3>Shared Variables</h3>
                <span className="shared-vars-panel__count">
                    {variables.length} resolved · {groups.length} group{groups.length !== 1 ? 's' : ''}
                </span>
            </div>

            <p className="shared-vars-panel__hint">
                Effective variables merged from every shared group attached to this
                resource. Later-attached groups override earlier ones on key
                collisions. Secret values are masked.
            </p>

            {variables.length > 5 && (
                <div className="shared-vars-panel__filter">
                    <input
                        type="text"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        placeholder="Filter variables…"
                    />
                </div>
            )}

            {filtered.length === 0 ? (
                <div className="shared-vars-panel__empty">
                    {filter
                        ? 'No matching variables'
                        : 'No shared variable groups attached to this resource yet.'}
                </div>
            ) : (
                <table className="shared-vars-table">
                    <thead>
                        <tr>
                            <th>Key</th>
                            <th>Value</th>
                            <th>Source group</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((v) => (
                            <tr key={v.key} className={v.is_secret ? 'is-secret' : ''}>
                                <td className="shared-vars-table__key">{v.key}</td>
                                <td className="shared-vars-table__value">{v.value}</td>
                                <td className="shared-vars-table__group">{v.group_name}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
};

export default EnvironmentVariablesPanel;
