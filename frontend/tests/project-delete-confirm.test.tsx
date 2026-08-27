/**
 * Deleting a saved project must take more than one stray tap.
 *
 * A project holds a whole study — the sites, the radio, the terrain
 * assumptions someone spent an afternoon on — and the portfolio list put an
 * unguarded 🗑 next to every row. On a tablet, next to Open and Duplicate,
 * that is how people lose work. The guard is inline and names the project
 * rather than a modal, because a modal is dismissed reflexively.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const deleteProject = vi.fn();
const listProjects = vi.fn();

const PROJECT = {
  id: 7, name: 'Quarry north ring', kind: 'coverage', data: {},
  share_token: null, share_expires_at: null,
  created_at: 1_700_000_000, updated_at: 1_700_000_000,
};
const USER = {
  id: 1, email: 'a@b.io', name: 'A', role: 'manager', tier: 'pro',
  org_name: 'ACME', has_logo: false,
};

vi.mock('@/lib/saas', () => ({
  deleteProject: (...a: unknown[]) => deleteProject(...a),
  listProjects: (...a: unknown[]) => listProjects(...a),
  duplicateProject: vi.fn(),
  shareProject: vi.fn(),
  unshareProject: vi.fn(),
  setTier: vi.fn(),
  uploadLogo: vi.fn(),
  fetchMe: () => Promise.resolve(USER),
  fetchAudit: () => Promise.resolve([]),
  fetchCosts: () => Promise.resolve(null),
}));

import Dashboard from '@/app/dashboard/page';

beforeEach(() => {
  deleteProject.mockReset().mockResolvedValue(undefined);
  listProjects.mockReset().mockResolvedValue([PROJECT]);
});

async function open() {
  render(<Dashboard />);
  await waitFor(() => screen.getByText('Quarry north ring'));
}

describe('deleting a saved project', () => {
  it('does not delete on the first click', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Delete Quarry north ring/i }));
    expect(deleteProject).not.toHaveBeenCalled();
    // What it asks for instead is unmistakable.
    expect(screen.getByRole('button', { name: /Delete permanently/i })).toBeTruthy();
  });

  it('deletes once confirmed, and says which project went', async () => {
    listProjects.mockResolvedValueOnce([PROJECT]).mockResolvedValue([]);
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Delete Quarry north ring/i }));
    fireEvent.click(screen.getByRole('button', { name: /Delete permanently/i }));

    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith(7));
    await waitFor(() => screen.getByText(/Quarry north ring.*deleted/i));
  });

  it('can be backed out of without losing the project', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: /Delete Quarry north ring/i }));
    fireEvent.click(screen.getByRole('button', { name: /^Cancel$/i }));

    expect(deleteProject).not.toHaveBeenCalled();
    expect(screen.getByText('Quarry north ring')).toBeTruthy();
    // Back to the ordinary row, not stuck in the armed state.
    expect(screen.queryByRole('button', { name: /Delete permanently/i })).toBeNull();
  });
});
