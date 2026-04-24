# Script Descriptions

## auto_config.py

This script runs continuously on a Raspberry Pi to dynamically update Node-RED's flows.json file based on incoming MQTT messages on the '/system/reporting' topic. It detects new devices (e.g., with lights, switches, or sensors) from the messages, adds corresponding Node-RED nodes (e.g., UI elements, MQTT in/out, functions) to the flows if the device is new, writes the updated flows back to disk, and restarts Node-RED to apply changes. The script ensures no duplicates by checking for existing device IDs in the flows.

### Key Functionality:
1. Loads the initial flows.json into memory.
2. Subscribes to the MQTT topic '/system/reporting' using paho-mqtt.
3. On receiving a message:
   - Parses the JSON payload.
   - Ignores invalid JSON or messages from 'node-red'.
   - Checks if the device_id already exists in flows (by ui_group name or topics).
   - If new, adds nodes for lights, switches, and sensors.
4. For lights:
   - Handles 'dual_temp' for dual-temperature pairs (pairs from highest indices, controlling lower index gets UI for toggle, brightness, temperature; higher skipped).
   - Adds ui_button (toggle), ui_slider (brightness, and temperature if dual), function nodes, and mqtt out in Virtual Links tab.
   - Adds mqtt out in Physical Links tab only for non-skipped lights.
   - UI order grouped by light: toggle, brightness, temperature.
5. For switches:
   - Adds mqtt in nodes in Physical Links tab, unwired, with topics '/switches/{device_id}/S{index}/action'.
6. For sensors:
   - Adds mqtt in and ui_gauge in Virtual Links tab, with topics based on single/multi-field.
7. Reuses existing nodes (ui_tab, ui_group, ui_base, mqtt-broker ID) where possible.
8. Positions nodes with y increments of 40 from max y in each tab to avoid overlap.
9. Writes updated flows.json and runs 'node-red-restart'.
10. Logs errors to '/home/pi/node_red_errors.log' when logging is enabled.

### Assumptions and Dependencies:
- Runs on Raspberry Pi with Node-RED installed and flows.json at '/home/pi/.node-red/flows.json'.
- MQTT broker at '127.0.0.1:1883' (localhost).
- Requires libraries: json, uuid, logging, subprocess, time, paho.mqtt.client (install via pip if needed).
- Virtual Links tab ID: '0c14ff671dbe21a9', Physical Links: 'c384410fdb810ed6', UI tab: 'tab_lights'.
- Broker ID reused from existing mqtt-broker node.
- Dual_temp 0 or [] ignored; >0 creates pairs (e.g., for count=12, dual_temp=2: pairs L9-L10, L11-L12; UI only for L9, L11).
- Temperature sliders: 0-255, step 5, shared mqtt out with 'set_temperature {value}'.
- No internet access; pure local operation.
- Script runs indefinitely; handle interruptions gracefully.

### Usage:
Run with 'python3 this_script.py'. Ensure permissions for flows.json and node-red-restart.
Set ENABLE_LOGGING to True/False to enable/disable error logging.

## EzamaRaspiConfig.py

This script configures dual-temperature lights for a Raspberry Pi light and switch controller. It prompts the user for the number of dual-temperature light pairs (0-6), updates the configuration in 'rpi_switch_light_mqtt2.py', stops and restarts the running script, replaces Node-RED flows with 'init_flows.json', and restarts Node-RED.

### Key Functionality:
1. Prompts for number of dual-temperature lights (0-6).
2. Warns about overwriting rpi_switch_light_mqtt2.py, restarting the script, replacing flows.json, and restarting Node-RED.
3. Requires confirmation to proceed.
4. Updates 'dual_temp' value in rpi_switch_light_mqtt2.py using regex replacement.
5. Stops the running rpi_switch_light_mqtt2.py script (pkill).
6. Restarts rpi_switch_light_mqtt2.py in the background with logging.
7. Copies init_flows.json to ~/.node-red/flows.json.
8. Restarts Node-RED service (sudo systemctl restart nodered).
9. Prints success message.

### Assumptions and Dependencies:
- init_flows.json exists in the script directory.
- rpi_switch_light_mqtt2.py runs as a service or background process.
- Node-RED installed with systemctl service.
- Script run with sufficient permissions for sudo.

### Usage:
Run with 'python3 EzamaRaspiConfig.py'.

## WT32Hub1.2.ino (ESP32 Firmware)

This Arduino sketch runs on an ESP32-based WT32-ETH01 board, providing smart lighting control for up to 12 PWM-driven LED circuits with optional dual-temperature mixing (pairs from the highest indices downward). It handles 32 multiplexed push-button switches for local control and integrates via MQTT over Ethernet (no WiFi). Key features include OTA updates, EEPROM persistence for config, and debug logging.

### Hardware Setup:
- **Board**: WT32-ETH01 (ESP32 with LAN8720 Ethernet PHY).
- **PWM Driver**: PCA9685 (I2C on pins 14/15) for lights (channels 1-12 used).
- **Buttons**: Two CD74HC4067 multiplexers for 32 active-low buttons (MUX1 on GPIO 5, MUX2 on GPIO 2).
- **Ethernet**: LAN8720 PHY (pins: MISO=16, MOSI=23, SCLK=18, CS=1, CLK=0_IN).

### Functionality:
- **Lights**: On/off, brightness (5-100%), temperature (0=cool/6500K to 255=warm/2700K). Dual-temp pairs ignore even channels for commands.
- **Buttons**: Debounced state machine for click (toggle), hold (brighten/dim), click+hold (heat/cool).
- **MQTT Topics**:
  - Subscribes: `/lights/{DEVICE_ID}/+/command` (JSON or legacy strings), `/lights/{DEVICE_ID}/dual/command` (sets dual_temp 0-6), `/system/broadcast` (ping).
  - Publishes: `/switches/{DEVICE_ID}/S{1-16}/action`, `/system/reporting` (ping response with config), `/system/debug` (logs).
- **Persistence**: EEPROM stores DEVICE_ID (8 alnum chars) and DUAL_TEMP_LIGHTS (0-6).
- **Boot**: Lights off at defaults; no test to preserve MQTT-retained states.
- **Loop**: OTA, MQTT, button scan (~50ms).

### Integration:
- Node-RED uses retained MQTT for state restoration.
- Debug via MQTT subscription.
- Version 1.2 (Ethernet fixes for ESP32 Arduino core v3+).
- Limitations: Fixed broker IP (192.168.99.1:1883), no auth.

### Usage:
Flash via Arduino IDE (board: ESP32 Dev Module, Ethernet config). OTA updates supported post-flash.