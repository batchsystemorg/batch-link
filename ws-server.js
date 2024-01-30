const WebSocket = require('ws');
const axios = require('axios');
const https = require('https');
const fs = require('fs');

const wss = new WebSocket.Server({ port: 3777 });

wss.on('connection', (ws, req) => {
  const clientIP = req.connection.remoteAddress.replace('::ffff:', '');
  console.log(`Client connected from IP: ${clientIP}`);
  console.log('sending WS message to get Printer Status')

  const command =  {
    action: 'print',
    content: 'http://batch.space/paperclip.gcode'
  }
  // ws.send(JSON.stringify(command))


  ws.on('message', (message) => {
    console.log('Raw message incoming: ', message)
    try {
      const data = JSON.parse(message);
      console.log(`Received from ${clientIP}:`, data);
      if (data.action === 'auth') {
        console.log('Received authentication response:', data.content)
        // check if that can be found in the DB and assign it to the PrinterModel
      } else {
        console.log('Unknown command:', data);
      } 
    } catch (error) {
      console.error(`Error parsing JSON: ${error}`);
    }
  }); 

  ws.on('close', () => {
    console.log(`Client from IP ${clientIP} disconnected`);
  });
});

console.log('WebSocket server is running on port 3777');