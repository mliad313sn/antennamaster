/**
 * SortablePanels — the drag-and-drop sidebar arranger. Verifies the arrange
 * toggle, keyboard reordering (↑/↓ on the handle), hide/show, order + hidden
 * persistence to localStorage, and that a saved layout is restored on mount.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it } from 'vitest';

import SortablePanels, { type SortablePanelItem } from '@/components/SortablePanels';

const KEY = 'test_layout';

function items(): SortablePanelItem[] {
  return [
    { id: 'a', label: 'Alpha', node: <div className="panel"><h3>Alpha panel</h3></div> },
    { id: 'b', label: 'Bravo', node: <div className="panel"><h3>Bravo panel</h3></div> },
    { id: 'c', label: 'Charlie', node: <div className="panel"><h3>Charlie panel</h3></div> },
  ];
}

function panelIds(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[data-panel-id]'))
    .map((el) => el.getAttribute('data-panel-id')!);
}

describe('SortablePanels', () => {
  beforeEach(() => localStorage.clear());

  it('renders panels in declared order, arrange controls hidden by default', () => {
    const { container } = render(<SortablePanels items={items()} storageKey={KEY} />);
    expect(panelIds(container)).toEqual(['a', 'b', 'c']);
    // Handles/eyes only appear once arranging.
    expect(container.querySelector('.drag-handle')).toBeNull();
    expect(screen.getByRole('button', { name: /Arrange panels/ })).toBeInTheDocument();
  });

  it('reorders a panel down via the move button and persists the new order', () => {
    const { container } = render(<SortablePanels items={items()} storageKey={KEY} />);
    fireEvent.click(screen.getByRole('button', { name: /Arrange panels/ }));

    // Move panel "a" down one slot via its explicit ▼ button (touch/SR-safe).
    fireEvent.click(screen.getByRole('button', { name: /Move Alpha down/ }));

    expect(panelIds(container)).toEqual(['b', 'a', 'c']);
    const saved = JSON.parse(localStorage.getItem(KEY)!);
    expect(saved.order).toEqual(['b', 'a', 'c']);
    // The move is announced to screen readers.
    expect(screen.getByText(/Moved Alpha to position 2 of 3/)).toBeInTheDocument();
  });

  it('keyboard-reorders via ↑/↓ on the drag handle', () => {
    const { container } = render(<SortablePanels items={items()} storageKey={KEY} />);
    fireEvent.click(screen.getByRole('button', { name: /Arrange panels/ }));
    const first = container.querySelector('[data-panel-id="a"]')!;
    const handle = within(first as HTMLElement).getByRole('button', { name: /Drag to reorder Alpha/ });
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    expect(panelIds(container)).toEqual(['b', 'a', 'c']);
  });

  it('disables the move buttons at the list boundaries', () => {
    render(<SortablePanels items={items()} storageKey={KEY} />);
    fireEvent.click(screen.getByRole('button', { name: /Arrange panels/ }));
    // First panel can't move up; last can't move down.
    expect(screen.getByRole('button', { name: /Move Alpha up/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Move Charlie down/ })).toBeDisabled();
  });

  it('hides a panel (dropping it from normal view) and restores it', () => {
    const { container } = render(<SortablePanels items={items()} storageKey={KEY} />);
    fireEvent.click(screen.getByRole('button', { name: /Arrange panels/ }));

    const second = container.querySelector('[data-panel-id="b"]')!;
    fireEvent.click(within(second as HTMLElement).getByRole('button', { name: /Hide panel/ }));
    expect(JSON.parse(localStorage.getItem(KEY)!).hidden).toContain('b');

    // Leave arrange mode: hidden panel is gone from the sidebar.
    fireEvent.click(screen.getByRole('button', { name: /Done/ }));
    expect(panelIds(container)).toEqual(['a', 'c']);
    // A badge advertises the hidden count on the toggle.
    expect(screen.getByRole('button', { name: /Arrange panels/ }).textContent).toContain('1');
  });

  it('restores a saved layout (order + hidden) on mount', () => {
    localStorage.setItem(KEY, JSON.stringify({ order: ['c', 'a', 'b'], hidden: ['a'] }));
    const { container } = render(<SortablePanels items={items()} storageKey={KEY} />);
    // 'a' is hidden, so normal view shows c then b in saved order.
    expect(panelIds(container)).toEqual(['c', 'b']);
  });

  it('appends newly-introduced panels without losing the saved order', () => {
    localStorage.setItem(KEY, JSON.stringify({ order: ['c', 'b'], hidden: [] }));
    const three = items();
    const { container, rerender } = render(
      <SortablePanels items={[three[1], three[2]]} storageKey={KEY} />);
    expect(panelIds(container)).toEqual(['c', 'b']);
    // 'a' shows up later (e.g. a state-gated panel): it appends, order kept.
    rerender(<SortablePanels items={three} storageKey={KEY} />);
    expect(panelIds(container)).toEqual(['c', 'b', 'a']);
  });
});
