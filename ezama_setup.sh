#!/bin/bash
# ezama_setup.sh
# Takes a fresh Raspberry Pi OS (Bookworm) install to a fully working Ezama node.
# Run as user pi, not root.
#
# Usage:
#   bash ezama_setup.sh [--wifi-ssid <ssid> --wifi-password <pass>] [--tailscale <auth-key>]
#
# Bootstrap on a fresh Pi (once SSH is reachable):
#   curl -sL https://raw.githubusercontent.com/bmullva/Ezama/main/ezama_setup.sh | bash -s -- --wifi-ssid MyNetwork --wifi-password secret

set -e

EZAMA_REPO="https://github.com/bmullva/Ezama.git"
EZAMA_DIR="/home/pi/Ezama"
TAILSCALE_KEY=""
WIFI_SSID=""
WIFI_PASSWORD=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --tailscale)     TAILSCALE_KEY="$2";  shift 2 ;;
    --wifi-ssid)     WIFI_SSID="$2";      shift 2 ;;
    --wifi-password) WIFI_PASSWORD="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "======================================================"
echo " Ezama Node Setup"
echo "======================================================"

echo "[1/10] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[2/10] Enabling I2C..."
sudo raspi-config nonint do_i2c 0

echo "[3/10] Installing mosquitto, hostapd, dnsmasq..."
sudo apt-get install -y mosquitto mosquitto-clients hostapd dnsmasq
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

echo "[4/10] Installing Node.js and Node-RED..."
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered) --confirm-install --confirm-pi --no-init
sudo systemctl enable nodered.service

echo "[5/10] Installing Node-RED contrib packages..."
mkdir -p /home/pi/.node-red
cd /home/pi/.node-red
npm install --save \
  node-red-contrib-buffer-parser@^3.2.2 \
  node-red-contrib-eztimer@~1.2.7 \
  node-red-contrib-ip@~1.0.1 \
  node-red-contrib-moment@~5.0.0 \
  node-red-contrib-play-audio@^2.5.0 \
  node-red-contrib-ui-multistate-switch@~1.2.3 \
  node-red-contrib-unit-converter@~0.0.3 \
  node-red-dashboard@~3.6.6 \
  node-red-node-pi-gpio@^2.0.7 \
  node-red-node-ping@^0.3.3 \
  node-red-node-random@^0.4.1 \
  node-red-node-serialport@^2.0.3 \
  node-red-node-smooth@^0.1.2 \
  node-red-node-twilio@~0.1.0 \
  node-red-node-ui-iframe@~0.2.1 \
  node-red-node-ui-table@~0.4.5
cd /home/pi

echo "[6/10] Installing Python packages..."
pip3 install --break-system-packages \
  adafruit-circuitpython-pca9685 adafruit-blinka RPi.GPIO smbus2 paho-mqtt 2>/dev/null || \
pip3 install \
  adafruit-circuitpython-pca9685 adafruit-blinka RPi.GPIO smbus2 paho-mqtt

echo "[7/10] Cloning Ezama repository..."
if [ -d "$EZAMA_DIR/.git" ]; then
  git -C "$EZAMA_DIR" pull
else
  rm -rf "$EZAMA_DIR"
  git clone -b main "$EZAMA_REPO" "$EZAMA_DIR"
fi
echo "sudo reboot" > "$EZAMA_DIR/restart.sh"
chmod +x "$EZAMA_DIR/restart.sh"

echo "[8/10] Configuring network (eth0 static, wlan0 AP, wlan1 client)..."

# hostapd: wlan0 open access point (SSID=EzamaSetup, no password)
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<'HOSTAPDCONF'
interface=wlan0
driver=nl80211
ssid=EzamaSetup
hw_mode=g
channel=1
beacon_int=200
dtim_period=3
disassoc_low_ack=0
HOSTAPDCONF
sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# dnsmasq: DHCP on eth0 (192.168.99.x) and wlan0 (192.168.98.x)
sudo tee /etc/dnsmasq.d/ezama-dhcp.conf > /dev/null <<'DNSMASQCONF'
# DHCP for wlan0 AP and eth0 wired subnets
interface=wlan0,eth0
bind-interfaces
no-resolv
log-dhcp

# wlan0 AP DHCP (192.168.98.x)
dhcp-range=wlan0,192.168.98.100,192.168.98.200,255.255.255.0,12h
dhcp-option=wlan0,option:router,192.168.98.1
dhcp-option=wlan0,option:dns-server,192.168.98.1

# eth0 wired DHCP (192.168.99.x)
dhcp-range=eth0,192.168.99.100,192.168.99.200,255.255.255.0,12h
dhcp-option=eth0,option:router,192.168.99.1
dhcp-option=eth0,option:dns-server,192.168.99.1
DNSMASQCONF

# NetworkManager: eth0 static 192.168.99.1/24
sudo nmcli connection delete eth0-static 2>/dev/null || true
sudo nmcli connection add type ethernet \
  con-name eth0-static \
  ifname eth0 \
  ipv4.addresses 192.168.99.1/24 \
  ipv4.method manual \
  ipv4.never-default yes \
  ipv4.route-metric 100 \
  ipv6.method ignore

# NetworkManager: wlan0 static 192.168.98.1/24 (NM sets IP; hostapd runs the AP)
sudo nmcli connection delete wlan0-ap-static 2>/dev/null || true
sudo nmcli connection add type wifi \
  con-name wlan0-ap-static \
  ifname wlan0 \
  ssid dummy-ap \
  802-11-wireless.mode infrastructure \
  ipv4.addresses 192.168.98.1/24 \
  ipv4.method manual \
  ipv6.method ignore \
  connection.autoconnect-priority 100

# NetworkManager: wlan1 client (upstream WiFi internet)
if [ -n "$WIFI_SSID" ]; then
  sudo nmcli connection delete "$WIFI_SSID" 2>/dev/null || true
  sudo nmcli connection add type wifi \
    con-name "$WIFI_SSID" \
    ifname wlan1 \
    ssid "$WIFI_SSID" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$WIFI_PASSWORD" \
    ipv4.method auto \
    ipv6.method auto
else
  echo "    WARNING: --wifi-ssid not provided. wlan1 (internet) not configured."
fi

# Enable and start network services
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo systemctl restart dnsmasq
sudo systemctl restart hostapd

echo "[9/10] Installing Node-RED flows..."
mkdir -p /home/pi/.node-red
if [ -f "$EZAMA_DIR/clean/init_flows.json" ]; then
  cp "$EZAMA_DIR/clean/init_flows.json" /home/pi/.node-red/flows.json
elif [ -f "$EZAMA_DIR/init_flows.json" ]; then
  cp "$EZAMA_DIR/init_flows.json" /home/pi/.node-red/flows.json
else
  echo "    WARNING: init_flows.json not found."
fi

echo "[10/10] Configuring crontab..."
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
