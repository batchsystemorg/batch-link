#!/bin/bash
# Define passwords
SSH_PASS="pingpong5"
SUDO_PASS="pingpong5"

# Loop from 002 to 045
for n in $(seq -f "%03g" 2 45); do
  host="bw-ldn-$n.local"
  echo "🔧 Updating $host ..."
  
  # Copy the updated script and resources
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/batch-link.py pi@$host:~/batch-link/
  sshpass -p "$SSH_PASS" scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/printercontroller pi@$host:~/batch-link/
  sshpass -p "$SSH_PASS" scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/utils pi@$host:~/batch-link/

  # Connect to Pi and execute commands
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pi@$host "
    echo '$SUDO_PASS' | sudo -S systemctl restart batch-link
  "

  echo "✅ $host has updated files and service has been restarted."
done

echo "🎉 All done."
