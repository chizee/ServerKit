import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { MoreHorizontal } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from './popover';
import { cn } from '@/lib/utils';

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef(({ className, children, ...props }, ref) => {
  const childArray = React.Children.toArray(children).filter(React.isValidElement);
  const containerRef = React.useRef(null);
  const triggerRefs = React.useRef([]);
  const moreBtnRef = React.useRef(null);
  const [hiddenIndices, setHiddenIndices] = React.useState([]);
  const [popoverOpen, setPopoverOpen] = React.useState(false);

  triggerRefs.current.length = childArray.length;

  const setContainerRef = React.useCallback(
    (node) => {
      containerRef.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [ref]
  );

  const recompute = React.useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const containerWidth = container.clientWidth;
    if (containerWidth === 0) return;

    // Measure each trigger's natural width. If currently hidden, un-hide briefly.
    const widths = triggerRefs.current.map((el) => {
      if (!el) return 0;
      const wasHidden = el.style.display === 'none';
      if (wasHidden) el.style.display = '';
      const w = el.offsetWidth;
      if (wasHidden) el.style.display = 'none';
      return w;
    });

    let active = -1;
    triggerRefs.current.forEach((el, i) => {
      if (el?.dataset?.state === 'active') active = i;
    });

    const moreWidth = moreBtnRef.current?.offsetWidth || 36;
    const gap = 8; // matches $space-2

    // All fit?
    const total = widths.reduce((s, w, i) => s + w + (i > 0 ? gap : 0), 0);
    if (total <= containerWidth) {
      setHiddenIndices((prev) => (prev.length === 0 ? prev : []));
      return;
    }

    // Reserve space for the More button.
    const budget = Math.max(0, containerWidth - moreWidth - gap);

    // Greedy left-to-right fit.
    const visible = [];
    let used = 0;
    for (let i = 0; i < widths.length; i++) {
      const cost = widths[i] + (visible.length > 0 ? gap : 0);
      if (used + cost <= budget) {
        visible.push(i);
        used += cost;
      } else {
        break;
      }
    }

    // Ensure active is visible — bring it forward if it would otherwise overflow.
    let visibleSet = visible;
    if (active !== -1 && !visible.includes(active)) {
      const others = [];
      let othersUsed = widths[active];
      for (let i = 0; i < widths.length; i++) {
        if (i === active) continue;
        const cost = widths[i] + (others.length === 0 ? gap : gap);
        if (othersUsed + cost <= budget) {
          others.push(i);
          othersUsed += cost;
        }
      }
      visibleSet = [...others, active].sort((a, b) => a - b);
    }

    const visibleSetObj = new Set(visibleSet);
    const hidden = [];
    for (let i = 0; i < widths.length; i++) {
      if (!visibleSetObj.has(i)) hidden.push(i);
    }
    setHiddenIndices((prev) => (arraysEqual(prev, hidden) ? prev : hidden));
  }, []);

  // Initial measurement after first paint (preserves SSR/first-paint contract).
  React.useEffect(() => {
    recompute();
  }, [recompute, childArray.length]);

  // Resize observer on the container.
  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => recompute());
    ro.observe(container);
    return () => ro.disconnect();
  }, [recompute]);

  // Re-run when active tab changes (so active never stays hidden).
  React.useEffect(() => {
    if (typeof MutationObserver === 'undefined') return;
    const observers = triggerRefs.current
      .map((el) => {
        if (!el) return null;
        const mo = new MutationObserver(() => recompute());
        mo.observe(el, { attributes: true, attributeFilter: ['data-state'] });
        return mo;
      })
      .filter(Boolean);
    return () => observers.forEach((o) => o.disconnect());
  }, [recompute, childArray.length]);

  const hiddenSet = new Set(hiddenIndices);

  return (
    <TabsPrimitive.List
      ref={setContainerRef}
      className={cn('tabs', className)}
      {...props}
    >
      {childArray.map((child, i) => {
        const isHidden = hiddenSet.has(i);
        return React.cloneElement(child, {
          key: child.key ?? i,
          ref: (el) => {
            triggerRefs.current[i] = el;
          },
          style: {
            ...(child.props.style || {}),
            display: isHidden ? 'none' : child.props.style?.display,
          },
          'data-overflow': isHidden ? 'hidden' : undefined,
        });
      })}
      {hiddenIndices.length > 0 && (
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <PopoverTrigger asChild>
            <button
              ref={moreBtnRef}
              type="button"
              className="tab tabs-overflow-trigger"
              aria-label="More tabs"
            >
              <MoreHorizontal size={16} />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            sideOffset={6}
            className="ui-popover-content"
          >
            <div className="tabs-overflow-list">
              {hiddenIndices.map((idx) => {
                const child = childArray[idx];
                const triggerEl = triggerRefs.current[idx];
                const isActive = triggerEl?.dataset?.state === 'active';
                return (
                  <TabsPrimitive.Trigger
                    key={`overflow-${child.key ?? idx}`}
                    type="button"
                    value={child.props.value}
                    disabled={child.props.disabled}
                    className="tabs-overflow-item"
                    data-state={isActive ? 'active' : 'inactive'}
                    onClick={(event) => {
                      child.props.onClick?.(event);
                      setPopoverOpen(false);
                    }}
                  >
                    {child.props.children}
                  </TabsPrimitive.Trigger>
                );
              })}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </TabsPrimitive.List>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn('tab', className)}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn('tab-content-pane', className)}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

function arraysEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
