#!/bin/bash

# Replace with your Node.js server IP and port
NODE_SERVER_IP="https://moonraker-api.onrender.com"
NODE_SERVER_PORT="3777"

# NODE_SERVER_IP="http://localhost"
# NODE_SERVER_PORT="10000"

curl -v "$NODE_SERVER_IP:$NODE_SERVER_PORT"
