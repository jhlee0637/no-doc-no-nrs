import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'offline-page.spec.ts',
  outputDir: '../etc/offline-demo/test-results',
  fullyParallel: true,
  workers: 2,
  reporter: 'list',
  use: {
    browserName: 'chromium',
    viewport: { width: 375, height: 812 },
    screenshot: 'only-on-failure',
  },
});
