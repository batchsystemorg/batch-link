# Install link to the internet on your printer
### Requirements
* Klipper and Moonraker needs to be running on your Pi
* You once need your Pi's local IP address, the username and password

### Installation
Run ```bash install-batch-link.sh``` in the Terminal and follow the instructions. Once done, you will get an IP address that you can use to add your printer to the Factory Manager.

### Helpful commands to troubleshoot, if needed
SSH into your Pi
```ssh username@ip-address```

Tell your SSH session what Terminal to emulate
```TERM=vt100```

See batch-link.service live logs
```journalctl -fu batch-link```
