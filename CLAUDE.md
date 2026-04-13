# Project: Ezama

## Overview
Home automation / IoT project running on a Raspberry Pi. Controls lights (including dual-color-temperature LED pairs), on/off valves, and floor heaters; collects sensor data. All devices communicate over MQTT. Node-RED provides the dashboard and flow logic; Python scripts on the Pi handle hardware I/O and dynamic Node-RED configuration.

---

## Folder Structure

| Path | Purpose |
|---|---|
| `/home/pi/Ezama/` | Main Python scripts and utilities |
| `/home/pi/Ezama/clean/` | Clean starting-point flows (`init_flows.json`) |
| `/home/pi/Ezama/arduino/` | Compiled `.bin` firmware for WT32-ETH01 ethernet devices |
| `/home/pi/.node-red/flows.json` | **LIVE** Node-RED flows — handle with extreme care |
| `/home/pi/Ezama/NODE/nodered.db` | Node-RED SQLite DB |

---

## Python Scripts

### `EzamaRaspiConfig.py` — Interactive System Reset / Reconfiguration Tool
Run manually (not at boot). Prompts the operator for the number of **dual-temperature light pairs** (0–6), then:
1. Patches the `"dual_temp"` value inside `rpi_switch_light_mqtt2.py`.
2. Kills and restarts `rpi_switch_light_mqtt2.py` (logs to `mqtt_script.log`).
3. Copies `init_flows.json` over the live `~/.node-red/flows.json`.
4. Restarts Node-RED via `systemctl`.

**Warning:** This obliterates the current Node-RED configuration. It prompts for `yes` confirmation before acting.

---

### `auto_config.py` — Auto Device Discovery / Node-RED Flow Populator
Started `@reboot` via crontab. Runs indefinitely.

Subscribes to the MQTT topic `/system/reporting`. When a new device announces itself (JSON payload), this script automatically adds the necessary Node-RED nodes to `flows.json` and restarts Node-RED — so devices appear in the dashboard without manual flow editing.

**What it adds per device type:**

- **Lights** (`/lights/<device_id>/L<n>/command`):
  - Virtual Links tab: toggle button, brightness slider (5–100), optional color-temperature slider (0–255) for dual-temp pairs, function nodes, and `mqtt out`.
  - Physical Links tab: `Interpret` function (state machine — on/off/click/set_brightness/set_temperature/start_\*/stop), 50 ms `inject` loop node, `Increment` function (ramps brightness/temperature for continuous actions), and `mqtt out` with `retain=true`.
  - Dual-temperature logic: pairs are assigned from the highest light indices downward (e.g., L11+L12 for one pair). The lower index (L11) gets the full UI; the higher (L12) is skipped in the UI and driven by the same command.

- **Switches** (`/switches/<device_id>/S<n>/action`):
  - Physical Links tab: `mqtt in` nodes, unwired (ready for Node-RED wiring to lights or other actions).

- **Sensors** (`/sensors/<device_id>/<type>/data[/<field>]`):
  - Virtual Links tab: `mqtt in` node wired to a `ui_gauge` per field.

Duplicate detection prevents re-adding existing devices. Errors logged to `/home/pi/node_red_errors.log`.

**Key constants (fixed in source):**
- MQTT broker: `127.0.0.1:1883`
- Virtual Links tab ID: `0c14ff671dbe21a9`
- Physical Links tab ID: `c384410fdb810ed6`

---

### `rpi_switch_light_mqtt2.py` — Raspberry Pi Light + Switch Controller
Started `@reboot` via crontab. Runs indefinitely.

Controls up to **12 light circuits** via a PCA9685 PWM driver (I²C: SCL=GPIO 3, SDA=GPIO 2) and reads **32 momentary buttons** via two 74HC4067 16-channel multiplexers (select pins GPIO 20–23; mux outputs GPIO 26 and 27, active-low with internal pull-ups).

**Button behavior (state machine: IDLE → PRESSED → CLICKED/HOLDING):**
- Even buttons (0, 2, …): "off" side — click sends `off`, hold sends `start_dim`, click-then-hold sends `start_cool`, release sends `stop`.
- Odd buttons (1, 3, …): "on" side — click sends `on`, hold sends `start_brighten`, click-then-hold sends `start_heat`, release sends `stop`.
- Click is defined as press < 400 ms; hold ≥ 400 ms; click-then-hold requires second press within 500 ms of first release.
- Debounce period: 50 ms.

**Light PWM:**
- Single-temperature: `PWM = (brightness/100) × 65535 × on_off`
- Dual-temperature (last `dual_temp` pairs from L12 downward): L(odd) drives 6500K channel, L(even) drives 2700K channel.
  - `PWM_6500K = on_off × (brightness/100) × (temperature/255) × 65535`
  - `PWM_2700K = on_off × (brightness/100) × ((255−temperature)/255) × 65535`
  - Temperature 0 = full warm (2700K), 255 = full cool (6500K).

**MQTT topics:**
- Subscribes: `/lights/RPi1/+/command` (JSON `{on_off, brightness, temperature}` or string commands), `/system/broadcast` (ping).
- Publishes: `/switches/RPi1/S<n>/action` (switch events), `/system/reporting` (ping response with device capabilities).

**Configuration** (top of file, edited by `EzamaRaspiConfig.py`):
```json
{
  "device_id": "RPi1",
  "version": "1.0",
  "lights": {"count": 12, "dual_temp": 2},
  "switches": 16,
  "sensors": []
}
```

Logs to `app.log`. Reconnects to MQTT indefinitely on failure. GPIO cleanup on exit.

---

### `restart.sh` — Daily Reboot Script
One line: `sudo reboot`. Run ~once per day via crontab to reset the system.

---

### `espota.py` — OTA Firmware Uploader
Standard Arduino ESP OTA tool (community script). Pushes a compiled `.bin` firmware file to a WT32-ETH01 device over ethernet:
```bash
python3 espota.py -i <ESP_IP> -I <Host_IP> -p <ESP_port> -P <Host_port> -f <sketch.bin>
```
Use this to deploy updated firmware from the `arduino/` folder to devices on the network.

---

## Arduino Firmware (WT32-ETH01 Devices)

All `.bin` files in `arduino/` are compiled ESP-IDF / Arduino firmware for the **WT32-ETH01** (ESP32 + LAN8720 ethernet). All devices:
- Connect via wired ethernet (no Wi-Fi).
- Use a local MQTT broker at `127.0.0.1:1883`.
- Respond to a `ping` message on `/system/broadcast` by publishing their capabilities JSON to `/system/reporting` (which `auto_config.py` listens to).
- Support OTA updates via `espota.py`.
- Store `DEVICE_ID` in EEPROM (falls back to a default if EEPROM is invalid).

### `WT32Hub1.2.ino.wt32-eth01.bin` — Light + Switch Hub (main controller device)
The most complex firmware. Mirrors the behavior of `rpi_switch_light_mqtt2.py` but runs on a standalone WT32-ETH01 board instead of the Raspberry Pi. Manages:
- **Lights**: PWM-controlled LED channels with brightness (5–100%) and color temperature (0–255 where 0=warm/2700K, 255=cool/6500K). Supports dual-temperature paired channels. `DUAL_TEMP_LIGHTS` is configurable and stored in EEPROM (updated live via MQTT).
- **Switches/buttons**: Reads physical buttons and publishes actions (`on`, `off`, `click`, `start_brighten`, `start_dim`, `start_cool`, `start_heat`, `stop`) to `/switches/<device_id>/S<n>/action`.
- **MQTT commands** subscribed on `/lights/<device_id>/+/command`: accepts both atomic JSON `{on_off, brightness, temperature}` and legacy string commands (`on`, `off`, `click`, `set_brightness <n>`, `set_temperature <n>`, `start_*`, `stop`). Commands to the "even" channel of a dual-temp pair are silently ignored (the odd/lower channel controls the pair).
- **Continuous actions** (brighten/dim/heat/cool) use a 50 ms loop — identical architecture to the Node-RED Physical Links increment logic.
- **Ping response** on `/system/reporting` includes lights count, dual_temp, switches count, sensors list.
- **Debug** output to `/system/debug`.

### `EthDS18B20-1.2.ino.wt32-eth01.bin` — DS18B20 Digital Temperature Sensor
Reads one or more **Dallas DS18B20** 1-Wire digital temperature sensors. Publishes temperature readings in °C to:
```
/sensors/<device_id>/DS18B20/data
```
Field name: `temperature_c`. Logs an error if the sensor is disconnected or fails to read.

### `EthJSNSR04T-1.1.ino.wt32-eth01.bin` / `EthJSNSR04T-1.2.ino.wt32-eth01.bin` — JSN-SR04T Waterproof Ultrasonic Water Level Sensor
Reads a **JSN-SR04T** waterproof ultrasonic sensor (typically mounted above a water tank or vessel) and publishes the measured distance to the water surface in centimeters to:
```
/sensors/<device_id>/JSNS-SR04T/data
```
Field name: `distance_to_water_cm`. Two versions exist (1.1 and 1.2 — use 1.2 unless a specific device requires 1.1).

### `EthMotionSensor-1.2.ino.wt32-eth01.bin` — RCWL-0516 Microwave Motion Sensor
Reads an **RCWL-0516** microwave radar motion detector. When motion state changes, publishes to:
```
/switches/<device_id>/S1/action
```
Reports state changes (e.g., detected / not detected). Integrated into the switch infrastructure so Node-RED can wire motion events to lights or other actions the same way physical switch presses are wired.

### `EthNTC10K-1.2.ino.wt32-eth01.bin` — NTC 10K Thermistor Temperature Sensor
Reads an analog **NTC 10 kΩ thermistor** (common for floor/room temperature measurement). Publishes temperature in °C to:
```
/sensors/<device_id>/NTC10K/data
```
Field name: `temperature_c`. Suitable for floor heating temperature feedback.

---

## System Architecture

```
Physical world
    │
    ├── Buttons/switches ──────────────────────────┐
    ├── WT32-ETH01 Hub (lights + switches)          │  MQTT /switches/.../action
    ├── WT32-ETH01 DS18B20 (temp)                  │  MQTT /sensors/.../data
    ├── WT32-ETH01 JSN-SR04T (water level)         │  MQTT /sensors/.../data
    ├── WT32-ETH01 NTC10K (floor temp)             │  MQTT /sensors/.../data
    ├── WT32-ETH01 Motion (RCWL-0516)              │  MQTT /switches/.../action
    └── RPi GPIO (lights + buttons via PCA9685)    │
                                                    ▼
                                        Mosquitto MQTT broker (127.0.0.1:1883)
                                                    │
                         ┌──────────────────────────┤
                         │                          │
                 auto_config.py              Node-RED flows.json
                 (populates flows              (dashboard UI,
                  for new devices)             switch→light logic,
                                               Physical Links loops)
                                                    │
                                        rpi_switch_light_mqtt2.py
                                        (PWM light output on Pi,
                                         button scanning on Pi)
```

---

## Device Notes
- WT32-ETH01 = ESP32 + LAN8720 wired ethernet. No Wi-Fi used.
- Firmware flashed via `espota.py` over ethernet (OTA).
- `device_id` stored in EEPROM on each device; verify before deploying duplicate IDs.

---

## Critical Rules for Claude

1. **ALWAYS backup before editing anything:**
   ```bash
   cp /home/pi/.node-red/flows.json /home/pi/.node-red/flows.json.bak.$(date +%Y%m%d_%H%M%S)
   ```

2. **`flows.json` is LIVE** — a mistake here could leave heaters running, valves open, or lights stuck on/off in a real home.

3. **Never push untested logic to live `flows.json`** — test using `clean/init_flows.json` first, then migrate carefully.

4. **Before changing Python scripts**, check how the change affects MQTT topics and Node-RED flow expectations — the Pi scripts and flows are tightly coupled.

5. **Before flashing new firmware**, verify the device IP, confirm the correct `.bin` file for the device type, and note which device it targets.

6. **`restart.sh` reboots the whole Pi** — this drops all MQTT connections momentarily and restarts all `@reboot` cron services.

7. **`EzamaRaspiConfig.py` destroys current flows** — never run it unless a full reset is intended.
