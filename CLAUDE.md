# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based printer connectivity service that enables remote control of 3D printers (Klipper/OctoPrint) through WebSocket connections. The service acts as a bridge between local printers and a remote factory management system.

## Core Architecture

- **Main Service**: `batch-link/batch-link.py` - Main application with WebSocket client for remote communication
- **Printer Controllers**: 
  - `printercontroller/klipper.py` - Moonraker API integration for Klipper printers
  - `printercontroller/octoprint.py` - OctoPrint API integration
- **Utilities**: `utils/helpers.py` - Shared helper functions and parsing utilities
- **Configuration**: `batch-link/batch-link.cfg` - Runtime configuration file

## Key Components

### BatchPrinterConnect Class
Main service class that manages:
- WebSocket connection to remote factory management system
- Printer driver abstraction (Klipper/OctoPrint)
- Periodic status updates and alive pings
- Command processing from remote server

### Printer Controllers
- Both controllers implement the same interface for printer operations
- Handle API communication with respective printer firmware
- Monitor printer status, temperatures, and job progress
- Support file uploads, print commands, and system control

### Command Processing
Remote commands supported:
- `print` - Download and print files
- `stop_print`, `pause_print`, `resume_print` - Print control
- `cmd` - Execute G-code commands
- `heat_printer`, `cool_printer` - Temperature control
- `move` actions - Manual extruder movement
- `reboot_system` - System reboot

## Development Commands

### Running the Service
```bash
python3 batch-link/batch-link.py
```

### Installing Dependencies
```bash
pip3 install -r batch-link/requirements.txt
```

### Service Management
```bash
# Start as systemd service
sudo systemctl start batch-link

# View logs
journalctl -fu batch-link

# Reload service after changes
sudo systemctl daemon-reload
sudo systemctl restart batch-link
```

## Configuration

The service requires `batch-link.cfg` with sections:
- `[printer_details]` - UUID, API_KEY, DRIVER (KLIPPER/OCTOPRINT)
- `[connection_settings]` - REMOTE_WS_URL, RECONNECT_INTERVAL

## Installation

Use the provided installer script:
```bash
bash installer.sh
```

This handles service installation, configuration, and systemd setup.

## Important Notes

- The service runs as a daemon and automatically reconnects on connection loss
- All printer communication is asynchronous using aiohttp
- Temperature and status updates are sent every 2 seconds when data changes
- The service supports both Klipper (via Moonraker) and OctoPrint printers
- System reboot functionality requires sudo permissions for the service user