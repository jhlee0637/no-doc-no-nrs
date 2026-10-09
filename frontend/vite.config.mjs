import { defineConfig } from 'vite';
import { prototypeServer } from './dev/prototype-server.mjs';

export default defineConfig({
  plugins: [prototypeServer()],
  server: {
    proxy: {
      '/api/coach': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
});
