'use client';

import { useEffect, useRef } from 'react';

/**
 * Shared dialog behavior for the app's modals: closes on Escape, moves focus
 * into the dialog on open, and returns focus to the previously focused
 * element on close — the WAI-ARIA dialog contract the four modal shells
 * share. Attach the returned ref to the `.modal` container (which must have
 * `tabIndex={-1}`).
 */
export function useDialog(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => {
      window.removeEventListener('keydown', esc);
      opener?.focus?.();
    };
  }, [onClose]);

  return ref;
}
