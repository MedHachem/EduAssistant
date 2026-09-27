// Regression guard for the "GET/PUT /api/... returns 404" bug: the
// Angular dev server's proxy (proxy.conf.json) and the Spring Boot
// backend's own server.port (application.properties) drifted apart --
// proxy.conf.json pointed at a port nothing was actually listening on
// (in that case, an unrelated local Apache httpd on port 8080 silently
// answered every /api request with its own 404 instead of the backend
// ever seeing the request). Both the controller mapping and the
// proxy's path prefix were correct; only the TARGET PORT the two files
// agreed on was wrong -- see backend/README.md's "404 regression"
// section for the full diagnosis.
//
// Parses both files (not just string-matching "8080") so this fails
// whenever they disagree, regardless of which one changes next.
//
// Run standalone: node scripts/verify-proxy-config.mjs
// Wired into: npm test (see package.json), so it runs on every test pass.
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(frontend, '../backend');

function portFromTarget(target) {
  const match = target.match(/:(\d+)\/?$/);
  if (!match) throw new Error(`Could not parse a port out of proxy target "${target}"`);
  return match[1];
}

function backendServerPort() {
  const path = join(backend, 'src/main/resources/application.properties');
  const properties = readFileSync(path, 'utf-8');
  const line = properties.split('\n').find((l) => l.trim().startsWith('server.port='));
  if (!line) throw new Error(`server.port not found in ${path}`);
  // Supports either "server.port=8081" or "server.port=${SERVER_PORT:8081}".
  const match = line.match(/server\.port=(?:\$\{[A-Z_]+:)?(\d+)\}?/);
  if (!match) throw new Error(`Could not parse a port out of "${line}"`);
  return match[1];
}

const proxy = JSON.parse(readFileSync(join(frontend, 'proxy.conf.json'), 'utf-8'));
const backendPort = backendServerPort();

let ok = true;
for (const key of ['/api', '/ws']) {
  const proxyPort = portFromTarget(proxy[key].target);
  if (proxyPort !== backendPort) {
    console.error(
      `[verify-proxy-config] MISMATCH: proxy.conf.json's "${key}" target is port ${proxyPort}, ` +
        `but backend/application.properties' server.port is ${backendPort}. ` +
        `/api requests from the Angular dev server will 404 (or hit an unrelated service) until these match.`,
    );
    ok = false;
  }
}

if (!ok) {
  process.exit(1);
}
console.log(`[verify-proxy-config] OK: proxy.conf.json and backend server.port agree on port ${backendPort}.`);
