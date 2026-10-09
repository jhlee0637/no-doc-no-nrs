// Package trusted Vite build output into one portable, network-free HTML file.
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(frontend, '..', 'etc', 'offline-demo');
const build = join(output, 'build');
const index = await readFile(join(build, 'index.html'), 'utf8');
const scriptMatch = index.match(/<script\b[^>]*src="([^"]+)"[^>]*><\/script>/);
const styleMatch = index.match(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/);
if (!scriptMatch || !styleMatch) throw new Error('The offline build must have one script and stylesheet.');

function assetPath(url) {
  if (!/^\/assets\/[A-Za-z0-9_.-]+$/.test(url)) throw new Error('Unexpected build asset path.');
  const result = resolve(build, url.slice(1));
  if (!result.startsWith(build + sep)) throw new Error('Asset must remain inside the build directory.');
  return result;
}

let script = await readFile(assetPath(scriptMatch[1]), 'utf8');
let style = await readFile(assetPath(styleMatch[1]), 'utf8');
// System fonts keep the portable file small and avoid external font loading.
style = style.replace(/@font-face\s*\{[^}]*\}/g, '')
  .replaceAll('"ChopCoach Noto","Noto Sans KR",', 'system-ui,');
const images = [...new Set(script.match(/\/assets\/[A-Za-z0-9_.-]+\.png/g) ?? [])];
if (images.length !== 2) throw new Error('Expected the two capture-guide PNG assets.');
for (const url of images) {
  const bytes = await readFile(assetPath(url));
  script = script.replaceAll(url, `data:image/png;base64,${bytes.toString('base64')}`);
}
if (/\b(?:import|export)\s/.test(script) || /import\s*\(/.test(script)) throw new Error('The portable script must be a complete bundle.');
if (/url\(/i.test(style)) throw new Error('Portable styles must not request font or image files.');
script = script.replace(/<\/script/gi, '<\\/script');
style = style.replace(/<\/style/gi, '<\\/style');
const hash = content => createHash('sha256').update(content).digest('base64');
const policy = `default-src 'none'; script-src 'sha256-${hash(script)}'; style-src 'sha256-${hash(style)}'; img-src data: blob:; font-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`;
// Bundle text can contain replacement tokens such as $&; insert it literally.
const html = index.replace(scriptMatch[0], () => `<script type="module">${script}</script>`)
  .replace(styleMatch[0], () => `<style>${style}</style>`)
  .replace('<head>', `<head>\n    <meta name="chopcoach-mode" content="offline">\n    <meta http-equiv="Content-Security-Policy" content="${policy}">\n    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E">`)
  .replace(/<title>[^<]*<\/title>/, '<title>ChopCoach · 사진 선택 화면 예시</title>');
const destination = join(output, 'ai-generated-chopcoach-offline.html');
await writeFile(destination, html);
const receipt = { file: 'etc/offline-demo/ai-generated-chopcoach-offline.html', bytes: Buffer.byteLength(html), sha256: createHash('sha256').update(html).digest('hex'), embedded_images: images.length, fonts: 'system', network_policy: 'connect-src none', source_mode: 'offline' };
await writeFile(join(output, 'ai-generated-build-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
process.stdout.write(JSON.stringify(receipt) + '\n');
