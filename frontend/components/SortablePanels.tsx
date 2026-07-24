'use client';

/**
 * SortablePanels — a dependency-free, drag-and-drop layout tool that lets the
 * user shape the planner sidebar into their own workspace: reorder the tool
 * panels AND hide the ones they never touch. Both choices persist to
 * localStorage, so the layout survives reloads (per-browser, no account).
 *
 * Why this exists: the sidebar stacks a dozen tool panels in a fixed order,
 * but different users live in different ones (a surveyor cares about the DXF
 * panel; a pre-sales engineer about coverage). "Arrange panels" turns each
 * panel into a draggable card — grab the ⠿ handle to move it, click the eye to
 * hide it — so everyone gets a sidebar that fits how they actually work.
 *
 * Design choices:
 * - No external DnD library: native HTML5 drag-and-drop keeps the bundle small
 *   and works offline (the app's whole point). An "armed" flag gates drags so
 *   they only start from the handle, never from a stray text selection.
 * - Opt-in arrange mode: while off, panels behave exactly as before (inputs,
 *   buttons, focus all normal) and hidden panels are simply absent. While on,
 *   every panel is shown (hidden ones dimmed) so nothing is lost, and panel
 *   bodies are inert so a drag can't accidentally toggle a control.
 * - Keyboard-accessible: the handle is a real <button>; ↑/↓ move its panel, so
 *   reordering never needs a mouse (drag-and-drop alone fails WCAG 2.1.1).
 * - Resilient order: transient panels (ones that appear only in some states,
 *   e.g. "Link analysis") keep their slot across show/hide because the saved
 *   order is a superset — ids are appended when first seen, never dropped, and
 *   rendering just filters to whatever is currently present.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export interface SortablePanelItem {
  /** Stable identity — drives React keys AND the persisted order. */
  id: string;
  /** Human label shown in the arrange overlay (e.g. when hidden). */
  label?: string;
  node: ReactNode;
}

export interface SortablePanelsProps {
  items: SortablePanelItem[];
  /** localStorage key for the saved layout (defaults to a planner-wide key). */
  storageKey?: string;
  arrangeLabel?: string;
  doneLabel?: string;
  resetLabel?: string;
  hint?: string;
  hideLabel?: string;
  showLabel?: string;
}

const DEFAULT_KEY = 'am_panel_layout_v1';

interface Layout { order: string[]; hidden: string[]; }

/** Merge a saved order with the live id set: keep saved ids first (in their
 *  saved order), then append any ids not yet seen. Never drops ids — a hidden
 *  or state-gated panel keeps its slot for when it returns. */
function reconcile(saved: string[], liveIds: string[]): string[] {
  const seen = new Set<string>();
  const merged: string[] = [];
  for (const id of saved) if (!seen.has(id)) { merged.push(id); seen.add(id); }
  for (const id of liveIds) if (!seen.has(id)) { merged.push(id); seen.add(id); }
  return merged;
}

/** Parse persisted layout; tolerates the legacy bare-array (order only). */
function parseLayout(raw: string | null): Layout {
  if (!raw) return { order: [], hidden: [] };
  try {
    const p = JSON.parse(raw);
    if (Array.isArray(p)) return { order: p, hidden: [] };
    return {
      order: Array.isArray(p?.order) ? p.order : [],
      hidden: Array.isArray(p?.hidden) ? p.hidden : [],
    };
  } catch { return { order: [], hidden: [] }; }
}

export default function SortablePanels({
  items, storageKey = DEFAULT_KEY,
  arrangeLabel = 'Arrange panels', doneLabel = 'Done',
  resetLabel = 'Reset', hideLabel = 'Hide panel', showLabel = 'Show panel',
  hint = 'Drag the ⠿ handle to reorder (or focus it and press ↑ / ↓); click the eye to hide a panel.',
}: SortablePanelsProps) {
  const liveIds = useMemo(() => items.map((i) => i.id), [items]);
  const liveKey = liveIds.join('|');

  const [order, setOrder] = useState<string[]>(liveIds);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [arrange, setArrange] = useState(false);
  // `armed` is the id currently allowed to start a native drag (set on handle
  // press). null everywhere else so panel bodies never initiate a drag.
  const [armed, setArmed] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const restored = useRef(false);

  const byId = useMemo(
    () => new Map(items.map((i) => [i.id, i])), [items]);

  // Load the saved layout once, reconciled against the current panel set.
  useEffect(() => {
    let saved: Layout = { order: [], hidden: [] };
    try { saved = parseLayout(localStorage.getItem(storageKey)); }
    catch { /* corrupted / unavailable storage: fall back to default */ }
    setOrder(reconcile(saved.order, liveIds));
    setHidden(new Set(saved.hidden));
    restored.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the order in sync when the live panel set changes (panels that mount
  // or unmount with app state), without losing the user's arrangement.
  useEffect(() => {
    setOrder((prev) => reconcile(prev, liveKey ? liveKey.split('|') : []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey]);

  // Persist after the initial restore (so we never clobber a saved layout with
  // the default before it has loaded).
  useEffect(() => {
    if (!restored.current) return;
    try {
      localStorage.setItem(storageKey,
        JSON.stringify({ order, hidden: Array.from(hidden) }));
    } catch { /* storage full/unavailable: layout is still live in memory */ }
  }, [order, hidden, storageKey]);

  function move(from: string, to: string) {
    if (from === to) return;
    setOrder((prev) => {
      const next = [...prev];
      const fi = next.indexOf(from);
      const ti = next.indexOf(to);
      if (fi < 0 || ti < 0) return prev;
      next.splice(fi, 1);
      next.splice(ti, 0, from);
      return next;
    });
  }

  function nudge(id: string, dir: -1 | 1) {
    // Move among currently-present panels (ignore absent ones for stepping).
    const present = order.filter((x) => byId.has(x));
    const i = present.indexOf(id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= present.length) return;
    move(id, present[j]);
  }

  function toggleHidden(id: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function resetLayout() {
    setArmed(null); setDragId(null); setOverId(null);
    setOrder(liveIds); setHidden(new Set());
    try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
  }

  // Present panels, in the user's order. When arranging, show every panel
  // (including hidden ones) so they can be restored; otherwise drop hidden.
  const present = order.filter((id) => byId.has(id));
  const ordered = arrange ? present : present.filter((id) => !hidden.has(id));
  const hiddenCount = present.filter((id) => hidden.has(id)).length;

  return (
    <div className="sortable-panels">
      <div className="sortable-toolbar" data-tour="arrange">
        <button
          type="button"
          className={`arrange-toggle${arrange ? ' active' : ''}`}
          aria-pressed={arrange}
          title={arrange ? doneLabel : arrangeLabel}
          onClick={() => { setArrange((v) => !v); setArmed(null); }}
        >
          <span aria-hidden="true">⠿</span> {arrange ? doneLabel : arrangeLabel}
          {!arrange && hiddenCount > 0 && (
            <span className="arrange-badge" title={`${hiddenCount} hidden`}>
              {hiddenCount}
            </span>
          )}
        </button>
        {arrange && (
          <button type="button" className="arrange-reset"
            onClick={resetLayout} title={resetLabel}>
            ↺ {resetLabel}
          </button>
        )}
      </div>
      {arrange && <p className="sortable-hint">{hint}</p>}

      {ordered.map((id) => {
        const item = byId.get(id)!;
        const isHidden = hidden.has(id);
        const isDragging = dragId === id;
        const isOver = overId === id && dragId !== null && dragId !== id;
        return (
          <div
            key={id}
            data-panel-id={id}
            className={
              'sortable-item'
              + (arrange ? ' arranging' : '')
              + (isDragging ? ' dragging' : '')
              + (isOver ? ' drop-target' : '')
              + (arrange && isHidden ? ' panel-hidden' : '')
            }
            draggable={arrange && armed === id}
            onDragStart={(e) => {
              if (!arrange || armed !== id) { e.preventDefault(); return; }
              setDragId(id);
              e.dataTransfer.effectAllowed = 'move';
              try { e.dataTransfer.setData('text/plain', id); } catch { /* Safari */ }
            }}
            onDragEnter={() => { if (dragId) setOverId(id); }}
            onDragOver={(e) => { if (dragId) e.preventDefault(); }}
            onDrop={(e) => {
              e.preventDefault();
              if (dragId) move(dragId, id);
              setDragId(null); setOverId(null); setArmed(null);
            }}
            onDragEnd={() => { setDragId(null); setOverId(null); setArmed(null); }}
          >
            {arrange && (
              <div className="sortable-controls">
                <button
                  type="button"
                  className="panel-vis"
                  aria-pressed={!isHidden}
                  aria-label={isHidden
                    ? `${showLabel}${item.label ? ` — ${item.label}` : ''}`
                    : `${hideLabel}${item.label ? ` — ${item.label}` : ''}`}
                  title={isHidden ? showLabel : hideLabel}
                  onClick={() => toggleHidden(id)}
                >
                  {isHidden ? '🚫' : '👁'}
                </button>
                <button
                  type="button"
                  className="drag-handle"
                  aria-label="Reorder panel — use up and down arrows"
                  title="Drag to reorder (or use ↑ / ↓)"
                  onMouseDown={() => setArmed(id)}
                  onTouchStart={() => setArmed(id)}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowUp') { e.preventDefault(); nudge(id, -1); }
                    else if (e.key === 'ArrowDown') { e.preventDefault(); nudge(id, 1); }
                  }}
                >
                  ⠿
                </button>
              </div>
            )}
            {/* While arranging, the panel body is inert (but visible) so a drag
                can't trip a control underneath the pointer; normal mode leaves
                it fully interactive. */}
            <div className={arrange ? 'sortable-body inert' : 'sortable-body'}>
              {item.node}
            </div>
          </div>
        );
      })}
    </div>
  );
}
