import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('.', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    css: false,
    // Unit/component tests only. e2e/ is Playwright's (real browser, real
    // backend) and its imports do not resolve under vitest, so the default
    // **/*.spec.ts glob must not reach it.
    include: ['tests/**/*.{test,spec}.{ts,tsx}'],
  },
});
