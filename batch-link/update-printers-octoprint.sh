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
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null /etc/systemd/system/batch-link.service pi@$host:/etc/systemd/system/batch-link.service
  
  # Connect to Pi and execute commands
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pi@$host "    
    # Create sudoers file for reboot permission if it doesn't exist
    echo '$SUDO_PASS' | sudo -S bash -c 'echo \"pi ALL=(ALL) NOPASSWD: /sbin/shutdown\" > /etc/sudoers.d/010_pi-nopasswd'
    
    # Make sure permissions are correct
    echo '$SUDO_PASS' | sudo -S chmod 440 /etc/sudoers.d/010_pi-nopasswd

    # Create/Overwrite venv
    echo '$SUDO_PASS' | sudo -S apt-get update
    echo '$SUDO_PASS' | sudo -S apt-get install -y python3-venv
    echo '$SUDO_PASS' | sudo -S apt-get install -y libopenblas0 libopenblas-dev
    python3 -m venv /home/pi/batch-link/venv
    source /home/pi/batch-link/venv/bin/activate
    pip install -r /home/pi/batch-link/requirements.txt
    
    # Restart the service
    echo '$SUDO_PASS' | sudo -S systemctl restart batch-link
  "
  echo "✅ $host updated."
done

echo "🎉 All printers from bw-ldn-002.local to bw-ldn-045.local have been updated!"