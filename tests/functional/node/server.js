'use strict';

const assert = require('assert/strict');
const crypto = require('crypto');
const dns = require('dns').promises;
const fs = require('fs').promises;
const http = require('http');
const os = require('os');
const path = require('path');
const { Worker } = require('worker_threads');
const { gzip, gunzip } = require('zlib');
const { promisify } = require('util');

const gzipAsync = promisify(gzip);
const gunzipAsync = promisify(gunzip);
const checks = [];
let ready = false;
const readinessWaiters = new Set();

function responseBody(status) {
  return JSON.stringify({ status, checks });
}

function send(response, statusCode, body) {
  response.writeHead(statusCode, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
  });
  response.end(body);
}

function waitForReadiness() {
  if (ready) return Promise.resolve();
  return new Promise((resolve) => {
    const waiter = () => {
      clearTimeout(timeout);
      readinessWaiters.delete(waiter);
      resolve();
    };
    const timeout = setTimeout(waiter, 5000);
    timeout.unref();
    readinessWaiters.add(waiter);
  });
}

function releaseReadinessWaiters() {
  for (const waiter of [...readinessWaiters]) waiter();
}

async function handleRequest(request, response) {
  const requestPath = new URL(request.url, 'http://localhost').pathname;

  if (requestPath === '/internal') {
    send(response, 200, JSON.stringify({ status: 'node-internal-ok' }));
    return;
  }

  if (requestPath !== '/') {
    send(response, 404, JSON.stringify({ status: 'not-found' }));
    return;
  }

  if (!ready) {
    await waitForReadiness();
    if (!ready) {
      send(response, 503, responseBody('starting'));
      return;
    }
  }

  send(response, 200, responseBody('node-app-ok'));
}

const server = http.createServer((request, response) => {
  handleRequest(request, response).catch((error) => {
    console.error('node request failed', error);
    if (!response.headersSent) send(response, 500, JSON.stringify({ status: 'request-failed' }));
    else response.destroy(error);
  });
});

async function runWorkerCheck() {
  const worker = new Worker(
    "const { parentPort } = require('worker_threads'); " +
      'parentPort.postMessage([1, 2, 3, 4, 5].reduce((sum, value) => sum + value * value, 0));',
    { eval: true },
  );

  const result = await new Promise((resolve, reject) => {
    worker.once('message', resolve);
    worker.once('error', reject);
    worker.once('exit', (code) => {
      if (code !== 0) reject(new Error(`worker exited with code ${code}`));
    });
  });
  await worker.terminate();
  assert.equal(result, 55);
}

async function runStartupChecks() {
  const configPath = process.env.DHI_CONFIG_PATH || '/app/app-config.json';
  const fileConfig = JSON.parse(await fs.readFile(configPath, 'utf8'));
  const config = { ...fileConfig, mode: process.env.DHI_APP_MODE || fileConfig.mode };
  assert.equal(fileConfig.mode, 'file');
  assert.equal(config.mode, 'environment');
  assert.equal(config.label, 'node-runtime');
  checks.push('config-precedence');

  const jsonValue = JSON.parse(JSON.stringify({ text: 'Zażółć ☃', count: 3 }));
  assert.deepEqual(jsonValue, { text: 'Zażółć ☃', count: 3 });
  checks.push('json');

  const temporaryDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'dhi-node-'));
  const temporaryFile = path.join(temporaryDirectory, 'probe.txt');
  try {
    await fs.writeFile(temporaryFile, 'node-filesystem-ok', 'utf8');
    assert.equal(await fs.readFile(temporaryFile, 'utf8'), 'node-filesystem-ok');
  } finally {
    await fs.rm(temporaryDirectory, { recursive: true, force: true });
  }
  checks.push('filesystem-tmp');

  const resolved = await dns.lookup('localhost');
  assert.ok(resolved.address);
  checks.push('dns');

  const digest = crypto.createHash('sha256').update('abc').digest('hex');
  assert.equal(digest, 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  checks.push('crypto');

  const compressed = await gzipAsync(Buffer.from('node-compression-ok', 'utf8'));
  assert.equal((await gunzipAsync(compressed)).toString('utf8'), 'node-compression-ok');
  checks.push('compression');

  assert.equal(Buffer.from('Zażółć', 'utf8').toString('utf8'), 'Zażółć');
  const utcHour = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    hour: '2-digit',
    hourCycle: 'h23',
  }).format(new Date('2020-01-01T00:00:00Z'));
  assert.equal(utcHour, '00');
  checks.push('encoding-timezone');

  await runWorkerCheck();
  checks.push('worker-thread');

  assert.equal(Reflect.apply(Math.max, null, [3, 9, 4]), 9);
  assert.ok(process.pid > 0);
  checks.push('reflection-native-runtime');
}

function listen() {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(8080, '0.0.0.0', resolve);
  });
}

function requestLocal(pathname) {
  return new Promise((resolve, reject) => {
    const request = http.get(`http://127.0.0.1:8080${pathname}`, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => {
        try {
          resolve({ statusCode: response.statusCode, body: JSON.parse(body) });
        } catch (error) {
          reject(error);
        }
      });
    });
    request.setTimeout(5000, () => request.destroy(new Error('local HTTP probe timed out')));
    request.on('error', reject);
  });
}

async function probeLocalHttp() {
  const internal = await requestLocal('/internal');
  assert.equal(internal.statusCode, 200);
  assert.equal(internal.body.status, 'node-internal-ok');

  const missing = await requestLocal('/missing');
  assert.equal(missing.statusCode, 404);
  assert.equal(missing.body.status, 'not-found');
}

async function start() {
  await runStartupChecks();
  await listen();
  await probeLocalHttp();
  checks.push('local-http');
  ready = true;
  releaseReadinessWaiters();
  console.log(`node startup checks passed: ${checks.join(',')}`);
}

function shutdown() {
  ready = false;
  releaseReadinessWaiters();
  if (!server.listening) process.exit(0);
  server.close(() => process.exit(0));
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

start().catch((error) => {
  console.error('node startup checks failed', error);
  releaseReadinessWaiters();
  if (server.listening) server.close(() => process.exit(1));
  else process.exit(1);
});
