// HTTP boundary shared by the localhost development and preview servers.
export const localHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "frame-ancestors 'none'",
};

// Keep Vite's defaults when extending the deny list (Vite 8.3.4).
export const privateFiles = [
  '.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml', '**/.git/**',
  '**/etc/**', '**/.ssh/**', '**/.aws/**', '**/.codex/**', '**/.agents/**',
  '*.{p7b,p8,jks,keystore,sqlite,sqlite3,db,log,map}',
];

function headerCount(request, name) {
  let count = 0;
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    if (request.rawHeaders[index].toLowerCase() === name) count++;
  }
  return count;
}

function privatePath(url) {
  const path = decodeURIComponent((url ?? '/').split('?')[0]).replaceAll('\\', '/');
  const segments = path.split('/');
  return segments.some(segment => /^(?:etc|\.git|\.ssh|\.aws|\.codex|\.agents)$/i.test(segment) ||
    /^\.env(?:\.|$)/i.test(segment) || /^(?:\.npmrc|\.yarnrc\.yml)$/i.test(segment)) ||
    /\.(?:crt|pem|key|p12|pfx|cer|der|p7b|p8|jks|keystore|sqlite|sqlite3|db|log|map)$/i.test(path);
}

export function localBoundary(fallbackPort) {
  return (request, response, next) => {
    for (const [name, value] of Object.entries(localHeaders)) response.setHeader(name, value);
    const port = request.socket.localPort ?? fallbackPort;
    const host = request.headers.host;
    const origin = request.headers.origin;
    const site = request.headers['sec-fetch-site'];
    const denied = headerCount(request, 'host') !== 1 ||
      (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) ||
      headerCount(request, 'origin') > 1 ||
      (origin !== undefined && origin !== `http://${host}`) ||
      (site !== undefined && !['none', 'same-origin', 'same-site'].includes(site));
    let code = denied ? 403 : 0;
    if (!code) {
      try { if (privatePath(request.url)) code = 403; }
      catch { code = 400; }
    }
    if (code) {
      response.statusCode = code;
      response.setHeader('Content-Type', 'text/plain; charset=utf-8');
      response.setHeader('Cache-Control', 'no-store');
      response.end(code === 403 ? 'Local request denied.' : 'Invalid request path.');
      return;
    }
    next();
  };
}

export function localhostBoundary() {
  return {
    name: 'chopcoach-localhost-boundary',
    enforce: 'pre',
    configResolved(config) {
      if (config.command !== 'serve') return;
      for (const options of [config.server, config.preview]) {
        if (options.host !== '127.0.0.1' || options.strictPort !== true || options.cors !== false) {
          throw new Error('The local frontend requires host 127.0.0.1, strictPort and CORS disabled.');
        }
      }
    },
    configureServer(server) {
      server.middlewares.use(localBoundary(server.config.server.port));
    },
    configurePreviewServer(server) {
      server.middlewares.use(localBoundary(server.config.preview.port));
    },
  };
}
