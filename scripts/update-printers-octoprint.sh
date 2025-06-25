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
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/requirements.txt pi@$host:~/batch-link/
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null /etc/systemd/system/batch-link.service pi@$host:/etc/systemd/system/
  sshpass -p "$SSH_PASS" scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/printercontroller pi@$host:~/batch-link/
  sshpass -p "$SSH_PASS" scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ~/batch-link/utils pi@$host:~/batch-link/

  # Connect to Pi and execute commands
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pi@$host "
    echo '$SUDO_PASS' | sudo -S bash -c 'echo \"pi ALL=(ALL) NOPASSWD: /sbin/shutdown\" > /etc/sudoers.d/010_pi-nopasswd'
    echo '$SUDO_PASS' | sudo -S chmod 440 /etc/sudoers.d/010_pi-nopasswd

    echo '$SUDO_PASS' | sudo -S apt-get update
    echo '$SUDO_PASS' | sudo -S apt-get install -y python3-venv libopenblas0 libopenblas-dev

    python3 -m venv ~/batch-link/venv
    source ~/batch-link/venv/bin/activate
    pip install -r ~/batch-link/requirements.txt

    # Move config file and modify it
    if [ -f ~/.octoprint/batch-link.cfg ]; then
      cp ~/.octoprint/batch-link.cfg ~/batch-link/batch-link.cfg

      # Insert DRIVER=OCTOPRINT before UUID
      sed -i '/^UUID=/i DRIVER=OCTOPRINT' ~/batch-link/batch-link.cfg
    else
      echo '⚠️  Config file not found on $host'
    fi

    echo '$SUDO_PASS' | sudo -S systemctl daemon-reload
    echo '$SUDO_PASS' | sudo -S systemctl restart batch-link
  "

  echo "✅ $host updated."
done

echo "🎉 All printers from bw-ldn-002.local to bw-ldn-045.local have been updated!"
