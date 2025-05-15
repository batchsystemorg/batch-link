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

mv batch-link.cfg /home/$username/moonraker
sudo mv /home/$username/batch-link/batch-link.service /etc/systemd/system/

echo -e "\033[0m "

service_file=/etc/systemd/system/batch-link.service
sudo sed -i "s|:::username|$username|g" "$service_file"

config_file=/home/$username/moonraker/batch-link.cfg
UUID=$(cat /proc/sys/kernel/random/uuid)
sudo sed -i "s|:::uuid|$UUID|g" "$config_file"

echo -e "Now installing python frameworks and we done."
pip install -q -r requirements.txt

sudo systemctl daemon-reload
sudo systemctl enable batch-link.service
sudo systemctl start batch-link.service
sudo systemctl restart batch-link.service

echo 'The batch-link plugin has been successfully installed on your printer and is now running.'
echo -e "\033[32m "
echo -e "Please add its UUID to your account to have it appear as a pritner"
echo -e "\033[32;1m${UUID}"
echo -e "\033[0m " 