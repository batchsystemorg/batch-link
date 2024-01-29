const express = require('express');
const app = express();

app.use((req, res, next) => {
  const clientIp = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
  console.log(`Connected device IP: ${clientIp}`);
  next();
});

// Your other routes and server logic here

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});
