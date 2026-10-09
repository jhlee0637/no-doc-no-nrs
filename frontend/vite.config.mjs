import { defineConfig } from 'vite';
import { prototypeServer } from './dev/prototype-server.mjs';

export default defineConfig({ plugins: [prototypeServer()] });
