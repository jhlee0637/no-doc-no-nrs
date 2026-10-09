import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import { prototypeServer } from './dev/prototype-server.mjs';
import { localhostBoundary, localHeaders, privateFiles } from './dev/ai-generated-local-boundary.mjs';

const frontendRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root: frontendRoot,
  plugins: [localhostBoundary(), prototypeServer()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    cors: false,
    forwardConsole: false,
    allowedHosts: ['127.0.0.1', 'localhost'],
    headers: localHeaders,
    fs: { strict: true, allow: [frontendRoot], deny: privateFiles },
    proxy: {
      '/api/coach': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    cors: false,
    allowedHosts: ['127.0.0.1', 'localhost'],
    headers: localHeaders,
  },
});
