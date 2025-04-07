#!/bin/bash
# Define passwords
SSH_PASS="pingpong5"
SUDO_PASS="pingpong5"

# Loop from 002 to 045
for n in $(seq -f "%03g" 2 45); do
  host="bw-ldn-$n.local"
  echo "🔧 Updating $host ..."
  
  # Copy the updated script
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/batch-link.py pi@$host:~/batch-link/batch-link.py
  
  # Connect to Pi and execute commands
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pi@$host "
    # Upgrade OpenCV as in the original script
    # echo '$SUDO_PASS' | sudo -S pip3 install --upgrade opencv-python-headless
    
    # Create sudoers file for reboot permission if it doesn't exist
    echo '$SUDO_PASS' | sudo -S bash -c 'echo \"pi ALL=(ALL) NOPASSWD: /sbin/shutdown\" > /etc/sudoers.d/010_pi-nopasswd'
    
    # Make sure permissions are correct
    echo '$SUDO_PASS' | sudo -S chmod 440 /etc/sudoers.d/010_pi-nopasswd
    
    # Restart the service
    echo '$SUDO_PASS' | sudo -S systemctl restart batch-link
  "
  echo "✅ $host updated, cv2 installed (headless), sudo privileges added, and service restarted!"
done

echo "🎉 All printers from bw-ldn-002.local to bw-ldn-045.local have been updated!"