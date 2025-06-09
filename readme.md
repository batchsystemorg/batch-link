# Install link to the internet on your printer
### Requirements
* Klipper or Octoprint

### Installation
Run ```bash install-batch-link.sh``` in the Terminal and follow the instructions. Once done, you will get an IP address that you can use to add your printer to the Factory Manager.

### Troubleshooting
SSH into your Pi: ```ssh username@ip-address```
Tell your SSH session what Terminal to emulate: ```TERM=vt100```
Watch batch-link.service live logs: ```journalctl -fu batch-link```

### Use OctoPi backup file (required for batchworks printers)
Instsall OctoPi on the Pi
Make sure WiFi data is in the setup config
Make sure it has a ***.local URL set so you can always easily find it on the local network