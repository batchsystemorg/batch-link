const express = require('express');
const app = express();
const port = process.env.PORT || 10000;


app.get("/", (req, res) => {
  console.log('get request received')
  const clientIp = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
  console.log(`Connected device IP: ${clientIp}`);
});


app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});
