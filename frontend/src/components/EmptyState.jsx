import { Inbox } from 'lucide-react';
import { Spinner } from './Spinner';

export default function EmptyState({
    icon: Icon = Inbox,
    title = 'No items found',
    description = '',
    action = null,
    size = 'default',
    loading = false
}) {
    if (loading) {
        return (
            <div className={`empty-state empty-state--${size}`}>
                <Spinner size={size === 'lg' ? 'lg' : 'md'} />
                {title && <h3 className="empty-state__title">{title}</h3>}
            </div>
        );
    }

    return (
        <div className={`empty-state empty-state--${size}`}>
            <div className="empty-state__icon">
                <Icon size={size === 'lg' ? 64 : 48} />
            </div>
            <h3 className="empty-state__title">{title}</h3>
            {description && (
                <p className="empty-state__description">{description}</p>
            )}
            {action && (
                <div className="empty-state__action">{action}</div>
            )}
        </div>
    );
}
