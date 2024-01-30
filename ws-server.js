const WebSocket = require('ws');
const axios = require('axios');
const fs = require('fs');

const wss = new WebSocket.Server({ port: 3777 });

wss.on('connection', (ws, req) => {
  const clientIP = req.connection.remoteAddress.replace('::ffff:', '');
  console.log(`Client connected from IP: ${clientIP}`);

  /*const command = {
    jsonrpc: '2.0',
    method: 'printer.objects.get',
    params: { objects: ['status'] },
    id: 1,
  };

  ws.send(JSON.stringify(command));*/
  const printerAddress = `https://${clientIP}`
  const getStatus = `/printer/objects/query?gcode_move&toolhead&extruder=target,temperature`;

  axios.get(printerAddress + getStatus)
    .then(response => {
      console.log(`Received response from printer: ${JSON.stringify(response.data)}`);
      printFile(printerAddress);
    })
    .catch(error => {
      console.error(`Error sending GET request to printer: ${error.message}`);
    });


  ws.on('message', (message) => {
    console.log(`Received from ${clientIP}: ${message}`);
  }); 

  ws.on('close', () => {
    console.log(`Client from IP ${clientIP} disconnected`);
  });
});

console.log('WebSocket server is running on port 3777');



const printFile = (printerAddress) => {
  const FormData = require('form-data');
  const formData = new FormData();
  const fileStream = fs.createReadStream('paperclip.gcode');
  console.log('file stream: ', fileStream)
  formData.append('file', fileStream, {
    filename: 'paperclip.gcode',
    contentType: 'application/octet-stream',
  });
  formData.append('print', 'true'); 

  axios({
    method: 'post',
    url: printerAddress + '/server/files/upload',
    data: formData,
    headers: {
      'Content-Type': `multipart/form-data; boundary=${formData._boundary}`,
    },
  })
    .then(response => {
      console.log('File transfer successful: ', response.data);
    })
    .catch(error => {
      console.error('File transfer failed: ', error);
    });
}