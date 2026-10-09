import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/offline-page.spec.ts',
  outputDir: '../etc/gui-prototype/test-results',
  fullyParallel: true,
  workers: 3,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'python3 -B -m backend.app.server --mode mock --port 8000',
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/coach/config',
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
    },
  ],
});
