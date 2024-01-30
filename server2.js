const express = require('express');
const app = express();
const port = process.env.PORT || 3777;


app.get("/", (req, res) => {
  console.log('get request received')
  const clientIp = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
  console.log(`Connected device IP: ${clientIp}`);
  return res.type('html').send(html)
});


const server = app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});

server.keepAliveTimeout = 120 * 1000;
server.headersTimeout = 120 * 1000;

server.on('exit', (code) => {
  console.log(`Server exited with code ${code}`);
});


process.on('uncaughtException', (err) => {
  console.error(`Uncaught Exception: ${err}`);
  // Restart the server
  server.close(() => {
    server.listen(port, () => {
      console.log(`Server restarted on port ${port}`);
    });
  });
});


const html = `
<!DOCTYPE html>
<html>
  <head>
    <title>Hello from Render!</title>
  </head>
</html>
`