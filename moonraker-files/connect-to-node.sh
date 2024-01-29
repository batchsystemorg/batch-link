#!/bin/bash

# Replace with your Node.js server IP and port
NODE_SERVER_IP="192.168.110.112"
NODE_SERVER_PORT="3000"

# Your connection logic here
# For example, you might use curl to make an HTTP request
curl "http://$NODE_SERVER_IP:$NODE_SERVER_PORT/connect"
