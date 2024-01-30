const WebSocket = require('ws');

const wss = new WebSocket.Server({ port: 3777 });

wss.on('connection', (ws, req) => {
  const clientIP = req.connection.remoteAddress;
  console.log(`Client connected from IP: ${clientIP}`);

  ws.on('message', (message) => {
    console.log(`Received from ${clientIP}: ${message}`);
  });

  ws.on('close', () => {
    console.log(`Client from IP ${clientIP} disconnected`);
  });
});

console.log('WebSocket server is running on port 3777');
