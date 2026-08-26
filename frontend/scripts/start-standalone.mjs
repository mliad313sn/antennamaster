// Start the production server.
//
// next.config.mjs sets `output: 'standalone'` for a minimal Docker image, and
// `next start` is NOT supported in that mode - it boots and serves HTML but
// cannot serve the client chunks, so the page renders once and then dies with
// a ChunkLoadError. (Next prints a warning about this, which is easy to miss
// in install output.) The supported entry point is .next/standalone/server.js,
// which needs the static assets and public/ copied in beside it - Next
// deliberately leaves that copy to the deployer.
//
// This script does both, so `npm start` matches what the docs promise.
import { cp, access, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const standalone = join(root, '.next', 'standalone');
const port = process.env.PORT || '3000';

const exists = async (p) => { try { await access(p); return true; } catch { return false; } };

if (!await exists(join(standalone, 'server.js'))) {
  console.error('[start] .next/standalone is missing — run `npm run build` first.');
  process.exit(1);
}

// Refresh the staged assets every start: a stale copy from an earlier build is
// exactly how you get chunk hashes that no longer resolve.
for (const [from, to] of [
  [join(root, '.next', 'static'), join(standalone, '.next', 'static')],
  [join(root, 'public'), join(standalone, 'public')],
]) {
  if (await exists(from)) {
    await rm(to, { recursive: true, force: true });
    await cp(from, to, { recursive: true });
  }
}

const child = spawn(process.execPath, ['server.js'], {
  cwd: standalone,
  stdio: 'inherit',
  env: { ...process.env, PORT: port, HOSTNAME: process.env.HOSTNAME || '0.0.0.0' },
});
child.on('exit', (code) => process.exit(code ?? 0));
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => child.kill(sig));
}
