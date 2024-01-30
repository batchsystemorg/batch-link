const express = require('express');
const app = express();
const port = process.env.PORT || 10000;


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


const html = `
<!DOCTYPE html>
<html>
  <head>
    <title>Hello from Render!</title>
  </head>
</html>
`