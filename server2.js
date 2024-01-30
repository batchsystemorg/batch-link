const express = require('express');
const app = express();
const port = process.env.PORT || 10000;


app.get("/", (req, res) => {
  console.log('get request received')
  const clientIp = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
  console.log(`Connected device IP: ${clientIp}`);
  return res.type('html').send(html)
});


app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});


const html = `
<!DOCTYPE html>
<html>
  <head>
    <title>Hello from Render!</title>
  </head>
</html>
`