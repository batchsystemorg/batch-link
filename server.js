const express = require('express');
const http = require('http');
const WebSocket = require('ws');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

wss.on('connection', (ws) => {
  console.log('WebSocket connected');

  ws.on('message', (message) => {
    console.log(`Received message: ${message}`);
    // Process the received message and perform actions if needed
  });

  // Send initial message to the printer
  ws.send('Hello, printer!');

  // You can send messages to the printer using ws.send()
  // Example: ws.send('G28'); // Send G-code command to the printer
});

const port = process.env.PORT || 3000;
server.listen(port, () => {
  console.log(`WebSocket server is running on port ${port}`);
});
