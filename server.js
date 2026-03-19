#!/usr/bin/env node
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT || 8902);
const API_TOKEN = process.env.API_TOKEN || '';
const ALLOW_ORIGINS = (process.env.ALLOW_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean);
const DATA_PATH = process.env.DATA_PATH || path.join(__dirname, 'data', 'metrics.json');
const STATIC_DIR = process.env.STATIC_DIR || __dirname;
const RATE_LIMIT_PER_MIN = Number(process.env.RATE_LIMIT_PER_MIN || 120);

const reqBucket = new Map();

function isRateLimited(ip) {
  const now = Date.now();
  const key = `${ip}:${Math.floor(now / 60000)}`;
  const cnt = (reqBucket.get(key) || 0) + 1;
  reqBucket.set(key, cnt);
  return cnt > RATE_LIMIT_PER_MIN;
}

function cleanBuckets() {
  const nowMin = Math.floor(Date.now() / 60000);
  for (const key of reqBucket.keys()) {
    const kMin = Number(key.split(':').pop());
    if (kMin < nowMin - 2) reqBucket.delete(key);
  }
}
setInterval(cleanBuckets, 30000).unref();

function setCors(req, res) {
  const origin = req.headers.origin || '';
  if (!origin) return;
  if (!ALLOW_ORIGINS.length || ALLOW_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  }
}

function unauthorized(res) {
  res.writeHead(401, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify({ error: 'unauthorized' }));
}

function tooMany(res) {
  res.writeHead(429, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify({ error: 'rate_limited' }));
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
  '.svg':  'image/svg+xml',
};

function serveStatic(reqPath, res) {
  const filePath = path.join(STATIC_DIR, reqPath === '/' ? 'index.html' : reqPath);
  // prevent path traversal
  if (!filePath.startsWith(STATIC_DIR)) {
    res.writeHead(403); return res.end();
  }
  try {
    const data = fs.readFileSync(filePath);
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    return res.end(data);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    return res.end('Not found');
  }
}

const server = http.createServer((req, res) => {
  setCors(req, res);

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  const ip = req.socket.remoteAddress || 'unknown';
  if (isRateLimited(ip)) return tooMany(res);

  const u = new URL(req.url, `http://${req.headers.host || `${HOST}:${PORT}`}`);

  if (u.pathname === '/healthz') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(JSON.stringify({ ok: true, ts: Date.now() }));
  }

  if (u.pathname === '/api/data') {
    if (API_TOKEN) {
      const headerToken = req.headers['x-api-key'] || '';
      const queryToken = u.searchParams.get('token') || '';
      if (headerToken !== API_TOKEN && queryToken !== API_TOKEN) {
        return unauthorized(res);
      }
    }
    try {
      const raw = fs.readFileSync(DATA_PATH, 'utf8');
      res.writeHead(200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
        Pragma: 'no-cache',
        Expires: '0',
      });
      return res.end(raw);
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      return res.end(JSON.stringify({ error: 'read_failed', message: String(err.message || err) }));
    }
  }

  // fallback: serve static files
  return serveStatic(u.pathname, res);
});

server.listen(PORT, HOST, () => {
  console.log(`maltese listening on http://${HOST}:${PORT}`);
  console.log(`static dir: ${STATIC_DIR}`);
  console.log(`data path: ${DATA_PATH}`);
  if (API_TOKEN) console.log('api token: enabled');
  if (ALLOW_ORIGINS.length) console.log(`cors allowlist: ${ALLOW_ORIGINS.join(', ')}`);
});
