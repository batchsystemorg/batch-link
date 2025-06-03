#!/bin/bash
# Define passwords
SSH_PASS="pingpong5"
SUDO_PASS="pingpong5"

# Loop from 002 to 045
for n in $(seq -f "%03g" 2 45); do
  host="bw-ldn-$n.local"
  echo "🔧 Restarting service on $host ..."
  
  # Connect to Pi and execute commands
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pi@$host "    
  
    # Restart the service
    echo '$SUDO_PASS' | sudo -S systemctl daemon-reload
    echo '$SUDO_PASS' | sudo -S systemctl restart batch-link
  "
  echo "✅ $host service restarted."
done

echo "🎉 All printers from bw-ldn-002.local to bw-ldn-045.local have restarted their service!"