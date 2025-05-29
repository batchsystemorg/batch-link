#!/bin/bash
echo -e "\033[0m "
echo -e "\033[0m "
echo -e "\033[0m "
echo -e "\033[32m"
echo -e "************************************"
echo -e "******* We are on the Pi now *******"
echo -e "************************************"
echo -e "\033[0m "
echo -e "\033[0m "
username=`whoami`

echo -e "\033[0mAnd we need the password one last time ⊂(◉‿◉)つ"

mv batch-link.cfg /home/$username/.octoprint
sudo mv /home/$username/batch-link/batch-link.service /etc/systemd/system/

echo -e "\033[0m "

service_file=/etc/systemd/system/batch-link.service
sudo sed -i "s|:::username|$username|g" "$service_file"

config_file=/home/$username/.octoprint/batch-link.cfg
UUID=$(cat /proc/sys/kernel/random/uuid)
sudo sed -i "s|:::uuid|$UUID|g" "$config_file"

echo -e "Now installing python frameworks and we done."
sudo apt-get update
sudo apt-get install python3-venv
sudo apt-get install -y libopenblas0 libopenblas-dev
python3 -m venv /home/$username/batch-link/venv
source /home/$username/batch-link/venv/bin/activate

if ! pip install -r /home/$username/batch-link/requirements.txt; then
    echo "❌ Failed to install Python requirements"
    exit 1
fi

sudo systemctl daemon-reload
sudo systemctl enable batch-link.service
sudo systemctl start batch-link.service
sudo systemctl restart batch-link.service

# Add reboot/shutdown permissions for the user
echo -e "\033[0mAdding reboot permissions for user: $username"
echo "$username ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown" | sudo tee -a /etc/sudoers > /dev/null

if [ $? -eq 0 ]; then
    echo -e "\033[32mReboot permissions added successfully"
else
    echo -e "\033[31mFailed to add reboot permissions"
fi

echo 'The batch-link plugin has been successfully installed on your printer and is now running.'
echo -e "\033[32m "
echo -e "Please add its UUID to your account to have it appear as a pritner"
echo -e "\033[32;1m${UUID}"
echo -e "\033[0m " 