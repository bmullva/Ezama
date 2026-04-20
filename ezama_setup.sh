#!/bin/bash
# ezama_setup.sh
# Takes a fresh Raspberry Pi OS (Bullseye/Bookworm) install to a fully
# working Ezama node. Run as user pi, not root.
#
# Usage:
#   bash ezama_setup.sh [--tailscale <auth-key>]
#
# Bootstrap on a fresh Pi (once SSH is reachable):
#   curl -sL https://raw.githubusercontent.com/bmullva/Ezama/master/ezama_setup.sh | bash

set -e

EZAMA_REPO="git@github.com:bmullva/Ezama.git"
EZAMA_DIR="/home/pi/Ezama"
TAILSCALE_KEY=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --tailscale) TAILSCALE_KEY="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "======================================================"
echo " Ezama Node Setup"
echo "======================================================"

echo "[1/9] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[2/9] Enabling I2C..."
sudo raspi-config nonint do_i2c 0

echo "[3/9] Installing mosquitto..."
sudo apt-get install -y mosquitto mosquitto-clients
sudo tee /etc/mosquitto/mosquitto.conf > /dev/null <<'MQTTCONF'
persistence true
persistence_location /var/lib/mosquitto/

log_dest file /var/log/mosquitto/mosquitto.log

include_dir /etc/mosquitto/conf.d

listener 1883
allow_anonymous true
MQTTCONF
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "[4/9] Installing Node.js and Node-RED..."
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered) --confirm-install --confirm-pi --no-init
sudo systemctl enable nodered.service

echo "[5/9] Installing Node-RED contrib packages..."
mkdir -p /home/pi/.node-red
cd /home/pi/.node-red
npm install --save   node-red-contrib-buffer-parser@^3.2.2   node-red-contrib-eztimer@~1.2.7   node-red-contrib-ip@~1.0.1   node-red-contrib-moment@~5.0.0   node-red-contrib-play-audio@^2.5.0   node-red-contrib-ui-multistate-switch@~1.2.3   node-red-contrib-unit-converter@~0.0.3   node-red-dashboard@~3.6.6   node-red-node-pi-gpio@^2.0.7   node-red-node-ping@^0.3.3   node-red-node-random@^0.4.1   node-red-node-serialport@^2.0.3   node-red-node-smooth@^0.1.2   node-red-node-twilio@~0.1.0   node-red-node-ui-iframe@~0.2.1   node-red-node-ui-table@~0.4.5
cd /home/pi

echo "[6/9] Installing Python packages..."
pip3 install --break-system-packages   adafruit-circuitpython-pca9685 adafruit-blinka RPi.GPIO smbus2 paho-mqtt 2>/dev/null || pip3 install   adafruit-circuitpython-pca9685 adafruit-blinka RPi.GPIO smbus2 paho-mqtt

echo "[7/9] Cloning Ezama repository..."
if [ -d "$EZAMA_DIR/.git" ]; then
  git -C "$EZAMA_DIR" pull
else
  git clone "$EZAMA_REPO" "$EZAMA_DIR"
fi
echo "sudo reboot" > "$EZAMA_DIR/restart.sh"
chmod +x "$EZAMA_DIR/restart.sh"

echo "[8/9] Installing Node-RED flows..."
mkdir -p /home/pi/.node-red
if [ -f "$EZAMA_DIR/clean/init_flows.json" ]; then
  cp "$EZAMA_DIR/clean/init_flows.json" /home/pi/.node-red/flows.json
elif [ -f "$EZAMA_DIR/init_flows.json" ]; then
  cp "$EZAMA_DIR/init_flows.json" /home/pi/.node-red/flows.json
else
  echo "    WARNING: init_flows.json not found."
fi

echo "[9/9] Configuring crontab..."
(crontab -l 2>/dev/null | grep -v 'Ezama\|restart.sh'; printf '0 2 * * * /home/pi/Ezama/restart.sh\n@reboot sleep 45 && /usr/bin/env python3 /home/pi/Ezama/rpi_switch_light_mqtt2.py\n@reboot sleep 90 && /usr/bin/env python3 /home/pi/Ezama/auto_config.py\n') | crontab -

if [ -n "$TAILSCALE_KEY" ]; then
  echo "[+] Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up --authkey "$TAILSCALE_KEY"
fi

echo ""
echo "======================================================"
echo " Setup complete! Rebooting in 10 seconds..."
echo " After reboot, Node-RED: http://$(hostname -I | awk '{print $1}'):1880"
echo "======================================================"
sleep 10
sudo reboot
