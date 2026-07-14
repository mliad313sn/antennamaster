import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Recharts' ResponsiveContainer and Leaflet both probe layout APIs that
// jsdom lacks; stub them so components mount.
class RO {
  observe() { /* noop */ }
  unobserve() { /* noop */ }
  disconnect() { /* noop */ }
}
(globalThis as Record<string, unknown>).ResizeObserver = RO;

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

// Default fetch mock: individual tests override per-URL as needed.
globalThis.fetch = vi.fn(async () => ({
  ok: true,
  status: 200,
  headers: new Headers(),
  json: async () => ({}),
  blob: async () => new Blob(),
  text: async () => '',
})) as unknown as typeof fetch;
