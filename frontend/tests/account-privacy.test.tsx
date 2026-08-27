/**
 * Account & privacy: erasure must be hard to do by accident, and easy to do
 * on purpose.
 *
 * The dangerous half of GDPR self-service is that "delete my account" is one
 * click away from "sign out" in every product that has it, and here the click
 * destroys uploaded site drawings and rendered studies as well as the login.
 * So the guard rails are the thing under test: a second screen, the password,
 * and the literal word DELETE.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import AccountPanel from '@/components/AccountPanel';
import type { User } from '@/lib/saas';

const eraseAccount = vi.fn();
const exportAccount = vi.fn();

vi.mock('@/lib/saas', () => ({
  eraseAccount: (...a: unknown[]) => eraseAccount(...a),
  exportAccount: (...a: unknown[]) => exportAccount(...a),
}));

const USER: User = {
  id: 7, email: 'subject@example.com', name: 'Data Subject', role: 'manager',
  tier: 'pro', org_name: 'ACME Mining', has_logo: false,
} as User;

function open() {
  return render(<AccountPanel user={USER} onClose={() => {}} onErased={() => {}} />);
}

describe('account & privacy', () => {
  it('does not expose the destructive action until it is asked for', () => {
    open();
    expect(screen.queryByLabelText(/Type DELETE/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Delete my account/i }));
    expect(screen.getByLabelText(/Type DELETE/i)).toBeTruthy();
  });

  it('refuses to erase until both the password and the word are given', () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: /Delete my account/i }));
    const go = screen.getByRole('button', { name: /Delete permanently/i });
    expect((go as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/^Password$/i),
      { target: { value: 'hunter22secure' } });
    expect((go as HTMLButtonElement).disabled).toBe(true);

    // A near-miss is still a miss - no lowercase, no "delete my account".
    fireEvent.change(screen.getByLabelText(/Type DELETE/i),
      { target: { value: 'delete' } });
    expect((go as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type DELETE/i),
      { target: { value: 'DELETE' } });
    expect((go as HTMLButtonElement).disabled).toBe(false);
    expect(eraseAccount).not.toHaveBeenCalled();
  });

  it('reports what was actually destroyed, not a bare confirmation', async () => {
    eraseAccount.mockResolvedValue({
      projects: 3, dxf: 1, antennas: 0, results: 12, logo: true,
      audit_pseudonymised: 48, subject: 'erased-abc',
    });
    open();
    fireEvent.click(screen.getByRole('button', { name: /Delete my account/i }));
    fireEvent.change(screen.getByLabelText(/^Password$/i),
      { target: { value: 'hunter22secure' } });
    fireEvent.change(screen.getByLabelText(/Type DELETE/i),
      { target: { value: 'DELETE' } });
    fireEvent.click(screen.getByRole('button', { name: /Delete permanently/i }));

    await waitFor(() => screen.getByText(/have been deleted/i));
    expect(eraseAccount).toHaveBeenCalledWith('hunter22secure');
    // A data-protection request has to be answerable with *what* went.
    expect(screen.getByText(/3 project/i)).toBeTruthy();
    expect(screen.getByText(/12 coverage result/i)).toBeTruthy();
    expect(screen.getByText(/48 audit/i)).toBeTruthy();
  });

  it('surfaces a rejected password instead of pretending it worked', async () => {
    eraseAccount.mockRejectedValue(new Error('Password does not match'));
    open();
    fireEvent.click(screen.getByRole('button', { name: /Delete my account/i }));
    fireEvent.change(screen.getByLabelText(/^Password$/i),
      { target: { value: 'wrong' } });
    fireEvent.change(screen.getByLabelText(/Type DELETE/i),
      { target: { value: 'DELETE' } });
    fireEvent.click(screen.getByRole('button', { name: /Delete permanently/i }));

    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByRole('alert').textContent).toMatch(/does not match/i);
  });

  it('builds the export in the page (the endpoint needs the bearer header)', async () => {
    exportAccount.mockResolvedValue({ account: { email: USER.email } });
    const createURL = vi.fn(() => 'blob:x');
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: createURL, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    open();
    fireEvent.click(screen.getByRole('button', { name: /Download my data/i }));
    await waitFor(() => screen.getByRole('status'));

    // A plain <a href="/api/auth/export"> would have downloaded a 401 page.
    expect(createURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalled();
    click.mockRestore();
  });
});
