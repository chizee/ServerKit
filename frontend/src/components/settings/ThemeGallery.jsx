import { Check } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import { DEFAULT_THEME_SLUG } from '../../data/bundledThemes';

// Theme Gallery — cards for every selectable skin (bundled seeds + installed).
// Apply is instant (tokens are already local); hovering a card previews it live
// and leaving restores the selected skin. Dark/light toggle stays orthogonal.
const ThemeGallery = () => {
    const { availableThemes, skin, setSkin, previewSkin, clearPreview } = useTheme();

    return (
        <div className="theme-gallery">
            {availableThemes.map((t) => {
                const isDefault = t.slug === DEFAULT_THEME_SLUG;
                const active = skin === t.slug;
                const swatches = Array.isArray(t.preview) ? t.preview.slice(0, 4) : [];
                return (
                    <button
                        type="button"
                        key={t.slug}
                        className={`theme-card${active ? ' theme-card--active' : ''}`}
                        onClick={() => setSkin(t.slug)}
                        onMouseEnter={() => previewSkin(isDefault ? null : t)}
                        onMouseLeave={clearPreview}
                        onFocus={() => previewSkin(isDefault ? null : t)}
                        onBlur={clearPreview}
                    >
                        <div className="theme-card__swatches">
                            {swatches.map((color, i) => (
                                <span
                                    key={i}
                                    className="theme-card__swatch"
                                    style={{ background: color }}
                                />
                            ))}
                        </div>
                        <div className="theme-card__meta">
                            <span className="theme-card__name">{t.name || t.slug}</span>
                            {t.base && <span className="theme-card__base">{t.base}</span>}
                        </div>
                        {t.description && (
                            <p className="theme-card__desc">{t.description}</p>
                        )}
                        {active && (
                            <span className="theme-card__applied">
                                <Check size={13} /> Applied
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
};

export default ThemeGallery;
