import { expect, test } from '@playwright/test';
import { isLocalAnalysisHost } from '../src/api/ai-generated-local-host';

test('analysis host permits loopback and private IPv4 while rejecting public and malformed hosts', () => {
  for (const host of ['localhost', '127.0.0.1', '[::1]', '10.0.0.1', '10.255.255.255', '172.16.0.1', '172.31.255.255', '192.168.0.1', '192.168.255.255']) {
    expect(isLocalAnalysisHost(host), host).toBe(true);
  }
  for (const host of ['example.com', '8.8.8.8', '172.15.255.255', '172.32.0.1', '192.169.1.1', '10.256.0.1', '10.0.1', '10.0.0.1.evil.test', '169.254.0.1', '100.64.0.1', '::1', '[fd00::1]', '']) {
    expect(isLocalAnalysisHost(host), host).toBe(false);
  }
});
