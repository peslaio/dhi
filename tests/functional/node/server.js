'use strict';

const http = require('http');

const server = http.createServer((_request, response) => {
  const body = JSON.stringify({ status: 'node-app-ok' });
  response.writeHead(200, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
  });
  response.end(body);
});

server.listen(8080, '0.0.0.0');

process.on('SIGTERM', () => server.close(() => process.exit(0)));
