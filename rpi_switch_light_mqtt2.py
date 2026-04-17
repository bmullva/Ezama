#!/usr/bin/env python3

"""
Raspberry Pi Light and Switch Controller

This script controls up to 12 light circuits and reads 32 momentary buttons on a Raspberry Pi, using MQTT for communication
and a PCA9685 for PWM control. It supports both single-temperature and dual-temperature lights. Continuous actions like
brightening and dimming are published via MQTT for external handling (e.g., Node-RED loops), matching the ESP32 WT32-ETH01
behavior. The system integrates with Node-RED for switch-to-light mapping, running locally on the Raspberry Pi alongside
the MQTT broker.

**Hardware Setup:**
- **Buttons**: 32 momentary switches, organized into 16 pairs (S1-S16), connected via two 74HC4067 multiplexers. Even buttons
 (0, 2, ..., 30) handle off/dim/cool; odd buttons (1, 3, ..., 31) handle on/brighten/heat. Multiplexer select pins are GPIO
20-23, with outputs on GPIO 26 (buttons 0-15) and 27 (buttons 16-31), using internal pull-ups.
- **Lights**: Up to 12 PWM channels controlled by a single PCA9685 (I2C: SCL=GPIO 3, SDA=GPIO 2). Dual-temperature light pair
s (0-6) are assigned from highest pins downward (e.g., L11-L12 for one pair). Light IDs L1-L12 map to PCA channels 1-12.
- **PWM Resolution**: Uses 8-bit input range (0-255) scaled to PCA9685’s 16-bit duty cycle range (0-65535).

**Software Design:**
- **State Machine**: Each button has a state machine (IDLE, PRESSED, CLICKED, HOLDING) to detect press patterns: clicks (<400
ms), holds (≥400ms), and click-then-hold sequences (within 500ms). A click publishes 'off' (even) or 'on' (odd); a hold
publishes 'start_dim'/'start_brighten'; click-then-hold publishes 'start_cool'/'start_heat'. Release publishes 'stop'.
- **Debouncing**: Software debouncing with a 50ms period filters noisy button inputs.
- **Timing**: Button scanning every ~50ms; no local continuous adjustments—actions are MQTT-published for external processing.
- **Error Handling**: Brightness (5-100) and temperature (0-255) values are clamped to valid ranges. Invalid light IDs are logged and ignored.

**Configuration:**
- Configuration is defined at the top of this script in a dictionary, including:
  - `device_id`: Unique identifier (e.g., 'RPi1').
  - `version`: Software version (e.g., '1.0').
  - `dual_temp_lights`: Number of dual-temperature light pairs (0-6).
  - `light_circuits`: Number of light circuits (12).
  - `switches`: Number of switch pairs (16).
  - `logging_enabled`: Boolean to toggle logging to a file for debugging.

**Messaging and MQTT Topics:**
- **Switch Actions**: Published to `/switches/<device_id>/<switch_id>/action` (e.g., `/switches/RPi1/S1/action`) with string
payloads:
  - `'start_brighten'`, `'start_dim'`, `'start_cool'`, `'start_heat'`: Start continuous actions (odd/even button holds).
  - `'stop'`: Stops continuous actions (button release).
  - `'on'`, `'off'`: Sets light on/off (odd/even button click).
- **Light Commands**: Subscribed on `/lights/<device_id>/<light_id>/command` (e.g., `/lights/RPi1/L1/command`) with payloads:
  - JSON: e.g., `{"on_off":"on","brightness":50,"temperature":128}` for atomic state updates.
  - Strings: `'on'`, `'off'`, `'click'` (toggle), `'set_brightness <value>'` (5-100), `'set_temperature <value>'` (0-255).
  - Unknown commands (e.g., 'start_*') are ignored/logged.
- **Broadcast and Reporting**:
  - Subscribed to `/system/broadcast` for `'ping'` messages.
  - Responds on `/system/reporting` with a JSON payload matching WT32 format: `{'device_id': 'RPi1', 'version': '1.0', 'ip': '192.168.1.100', 'lights': {'count': 12, 'dual_temp': 2}, 'switches': 16, 'sensors': []}`.
- **MQTT Broker**: Runs locally at `127.0.0.1:1883`, with indefinite reconnection attempts if the connection fails.

**Ping Response:**
- When a `'ping'` message is received on `/system/broadcast`, the script responds on `/system/reporting` with a JSON message containing the configuration and network IP address (eth0 or wlan0).

**Notes:**
- Node-RED handles switch-to-light mappings externally and loops continuous actions; the Raspberry Pi publishes actions but does not process them locally for consistency with WT32-ETH01.
- Logging is toggleable via the `logging_enabled` config flag, writing to a file (e.g., 'app.log') for debugging. PWM updates are logged at DEBUG level to reduce spam; key events (MQTT, button actions) use INFO.
- PWM calculations:
  - Single-temperature: `PWM = (brightness / 100.0) * 65535 * onOff`.
  - Dual-temperature (e.g., L11: 6500K cool, L12: 2700K warm): `PWM_6500K = onOff * (brightness / 100.0) * (temperature / 255.0) * 65535`, `PWM_2700K = onOff * (brightness / 100.0) * ((255 - temperature) / 255.0) * 65535`.
- Temperature note: Value 0 = warm (2700K/full 2700K channel), 255 = cool (6500K/full 6500K channel), based on Kelvin scale (higher K = cooler light).
"""

import RPi.GPIO as GPIO
import time
import json
import netifaces
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
from adafruit_pca9685 import PCA9685
from board import SCL, SDA
import busio
import logging

# Constants
SELECT_PINS = [20, 21, 22, 23]  # MUX select pins (s0-s3)
MUX1_PIN = 26  # MUX1 output (buttons 0-15)
MUX2_PIN = 27  # MUX2 output (buttons 16-31)
DEBOUNCE_TIME = 0.05  # 50ms debounce time
ACTION_THRESHOLD = 0.4  # 400ms to distinguish click vs. hold
CLICK_HOLD_WINDOW = 0.5  # 500ms for click-then-hold
ADJUST_INTERVAL = 0.05  # 50ms loop interval

# State machine states
IDLE = 0
PRESSED = 1
CLICKED = 2
HOLDING = 3

# Configuration
CONFIG = {
    "device_id": "RPi1",
    "version": "1.0",
    "lights": {"count": 12, "dual_temp": 2},
    "switches": 16,
    "sensors": []
}

# Initialize logging
if CONFIG.get("logging_enabled", True):
    logging.basicConfig(filename="app.log", level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Script started")
else:
    logging.getLogger().disabled = True

DEVICE_ID = CONFIG["device_id"]
LIGHT_CIRCUITS = CONFIG["lights"]["count"]
SWITCHES = CONFIG["switches"]
DUAL_TEMP_LIGHTS = CONFIG["lights"]["dual_temp"]

# MQTT setup
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_LIGHT = f"/lights/{DEVICE_ID}/+/command"
MQTT_TOPIC_BROADCAST = "/system/broadcast"
MQTT_TOPIC_REPORTING = "/system/reporting"

# Light states (size 13 to handle L1-L12, index 0 unused)
onOff = [0] * (LIGHT_CIRCUITS + 1)
brightness = [100] * (LIGHT_CIRCUITS + 1)
temperature = [0] * (LIGHT_CIRCUITS + 1)  # 0 = warm/2700K, 255 = cool/6500K

# Button states
buttonState = [IDLE] * (SWITCHES * 2)
pressStart = [0] * (SWITCHES * 2)
d_pin_reading = [1] * (SWITCHES * 2)
last_reading = [1] * (SWITCHES * 2)
last_debounce_time = [0] * (SWITCHES * 2)
last_click_time = [0] * (SWITCHES * 2)

# PCA9685 setup
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 1000  # Set PWM frequency to 1000Hz
for ch in range(16):  # Clear all channels
    pca.channels[ch].duty_cycle = 0

# GPIO setup
GPIO.setmode(GPIO.BCM)
for pin in SELECT_PINS:
    GPIO.setup(pin, GPIO.OUT)
GPIO.setup(MUX1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(MUX2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# MQTT client (global)
client = None

def on_connect(client, userdata, flags, reason_code, properties=None):
    logging.info(f"Connected to MQTT broker with code {reason_code}")
    if reason_code == 0:
        client.subscribe(MQTT_TOPIC_LIGHT)
        client.subscribe(MQTT_TOPIC_BROADCAST)
    else:
        logging.error(f"Connection failed: {reason_code}")

def on_message(client, userdata, msg, properties=None):
    topic = msg.topic
    payload = msg.payload.decode()
    logging.info(f"Received message on {topic}: {payload}")
    if topic == MQTT_TOPIC_BROADCAST and payload == "ping":
        send_ping_response()
    elif topic.startswith(f"/lights/{DEVICE_ID}/"):
        try:
            light_id_str = topic.split("/")[-2][1:]  # Extract light number string (e.g., '1' from 'L1')
            light_id = int(light_id_str)  # Map L1->1, L2->2, etc.
            handle_light_command(light_id, payload)
        except ValueError as e:
            logging.error(f"Invalid light_id format in topic {topic}: {e}")
        except Exception as e:
            logging.error(f"Error handling light command on {topic}: {e}")

def send_ping_response():
    ip_address = get_ip_address()
    response = {
        "device_id": DEVICE_ID,
        "version": CONFIG["version"],
        "ip": ip_address,
        "lights": CONFIG["lights"],
        "switches": CONFIG["switches"],
        "sensors": CONFIG["sensors"]
    }
    client.publish(MQTT_TOPIC_REPORTING, json.dumps(response))
    logging.info(f"Sent ping response: {response}")

def get_ip_address():
    interfaces = ["eth0", "wlan0"]
    for iface in interfaces:
        try:
            return netifaces.ifaddresses(iface)[netifaces.AF_INET][0]["addr"]
        except Exception:
            pass
    logging.warning("Could not get IP from eth0 or wlan0, defaulting to 127.0.0.1")
    return "127.0.0.1"

def handle_light_command(light_id, command):
    if not (1 <= light_id <= LIGHT_CIRCUITS):
        logging.warning(f"Invalid light_id {light_id}, ignoring command")
        return

    start_dual = max(1, (LIGHT_CIRCUITS + 1) - 2 * DUAL_TEMP_LIGHTS)
    if light_id % 2 == 0 and light_id >= start_dual:
        logging.warning(f"Command to even light_id {light_id} in dual pair ignored")
        return

    logging.info(f"Handling command for light {light_id}: {command}")

    updated = False

    # Check for JSON payload (atomic update)
    try:
        doc = json.loads(command)
        on_off_str = doc.get("on_off", "off")
        onOff[light_id] = 1 if on_off_str == "on" else 0
        bright_val = doc.get("brightness", 100)
        brightness[light_id] = max(5, min(100, bright_val))
        if is_dual_temp(light_id):
            temp_val = doc.get("temperature", 0)
            temperature[light_id] = max(0, min(255, temp_val))
        updated = True
        logging.info(f"Atomic JSON update for light {light_id}")
    except json.JSONDecodeError:
        # Fallback: Legacy string parsing
        if command == "on":
            onOff[light_id] = 1
            updated = True
        elif command == "off":
            onOff[light_id] = 0
            updated = True
        elif command == "click":
            onOff[light_id] = 1 - onOff[light_id]
            updated = True
        elif command.startswith("set_brightness "):
            parts = command.split()
            if len(parts) == 2:
                try:
                    value = int(parts[1])
                    brightness[light_id] = max(5, min(100, value))
                    updated = True
                except ValueError:
                    logging.error(f"Invalid brightness value: {parts[1]}")
            else:
                logging.error("Invalid set_brightness command format")
        elif command.startswith("set_temperature "):
            parts = command.split()
            if len(parts) == 2:
                try:
                    value = int(parts[1])
                    temperature[light_id] = max(0, min(255, value))
                    updated = True
                except ValueError:
                    logging.error(f"Invalid temperature value: {parts[1]}")
                else:
                    logging.error("Invalid set_temperature command format")
        # Ignore unknown commands like 'start_*' or 'stop' - handle externally via MQTT loops

    if updated:
        update_light_pwm(light_id)

def update_light_pwm(light_id):
    if is_dual_temp(light_id):
        pwm_6500K = int(onOff[light_id] * (brightness[light_id] / 100.0) * (temperature[light_id] / 255.0) * 65535)
        pwm_2700K = int(onOff[light_id] * (brightness[light_id] / 100.0) * ((255 - temperature[light_id]) / 255.0) * 65535)
        pca.channels[light_id].duty_cycle = pwm_2700K
        pca.channels[light_id + 1].duty_cycle = pwm_6500K
        logging.debug(f"Updated dual light {light_id}: 6500K PWM={pwm_6500K}, 2700K PWM={pwm_2700K}")
    else:
        pwm = int(onOff[light_id] * (brightness[light_id] / 100.0) * 65535)
        pca.channels[light_id].duty_cycle = pwm
        logging.debug(f"Updated single light {light_id}: PWM={pwm}")

def is_dual_temp(light_id):
    start_dual = max(1, (LIGHT_CIRCUITS + 1) - 2 * DUAL_TEMP_LIGHTS)
    return light_id >= start_dual and light_id % 2 == 1

def set_mux_channel(channel):
    for i in range(4):
        GPIO.output(SELECT_PINS[i], (channel >> i) & 1)

def read_switches():
    for i in range(16):
        set_mux_channel(i)
        time.sleep(0.00005)  # 50us delay for signal stabilization
        mux1_reading = GPIO.input(MUX1_PIN)
        mux2_reading = GPIO.input(MUX2_PIN)
        update_button_state(i, mux1_reading)
        update_button_state(i + 16, mux2_reading)

def update_button_state(button_id, current_reading):
    global buttonState, pressStart, d_pin_reading, last_reading, last_debounce_time, last_click_time

    now = time.time()

    # Debounce logic
    if current_reading != last_reading[button_id]:
        last_debounce_time[button_id] = now
        last_reading[button_id] = current_reading

    if now - last_debounce_time[button_id] > DEBOUNCE_TIME:
        if current_reading != d_pin_reading[button_id]:
            d_pin_reading[button_id] = current_reading
            if current_reading == 0:  # Button pressed (active low)
                print(f"Button {button_id} pressed")  # For manual testing
                logging.debug(f"Button {button_id} pressed, state={buttonState[button_id]}")
                if buttonState[button_id] == IDLE:
                    buttonState[button_id] = PRESSED
                    pressStart[button_id] = now
                elif buttonState[button_id] == CLICKED and now - last_click_time[button_id] < CLICK_HOLD_WINDOW:
                    buttonState[button_id] = HOLDING
                    action = "start_cool" if button_id % 2 == 0 else "start_heat"
                    publish_switch_action(button_id, action)
                    logging.debug(f"Button {button_id} click-then-hold, action={action}")
            else:  # Button released
                press_duration = now - pressStart[button_id]
                print(f"Button {button_id} released, duration={press_duration:.3f}s")  # For manual testing
                logging.debug(f"Button {button_id} released, duration={press_duration:.3f}s, state={buttonState[button_id]}")
                if buttonState[button_id] == PRESSED and press_duration < ACTION_THRESHOLD:
                    buttonState[button_id] = CLICKED
                    last_click_time[button_id] = now
                    logging.debug(f"Button {button_id} clicked")
                elif buttonState[button_id] in [PRESSED, HOLDING]:
                    publish_switch_action(button_id, "stop")
                    logging.debug(f"Button {button_id} stopped continuous action")
                    buttonState[button_id] = IDLE
                    logging.debug(f"Button {button_id} reset to IDLE")

        # Periodically check for CLICKED state timeout
        if buttonState[button_id] == CLICKED and now - last_click_time[button_id] >= CLICK_HOLD_WINDOW:
            action = "off" if button_id % 2 == 0 else "on"
            publish_switch_action(button_id, action)
            buttonState[button_id] = IDLE
            logging.debug(f"Button {button_id} CLICKED timeout, action={action}")

        # Hold detection for continuous actions
        if buttonState[button_id] == PRESSED and now - pressStart[button_id] >= ACTION_THRESHOLD:
            buttonState[button_id] = HOLDING
            action = "start_dim" if button_id % 2 == 0 else "start_brighten"
            publish_switch_action(button_id, action)
            logging.debug(f"Button {button_id} held, action={action}")

def publish_switch_action(button_id, action):
    switch_id = (button_id // 2) + 1  # S1 to S16
    topic = f"/switches/{DEVICE_ID}/S{switch_id}/action"
    client.publish(topic, action)
    logging.info(f"Published switch action: {topic} - {action}")

def connect_mqtt():
    global client
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            break
        except Exception as e:
            logging.error(f"Failed to connect to MQTT broker: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    return client

def main():
    connect_mqtt()
    client.loop_start()

    # Temporary light test code for manual hardware verification
    #for i in range(1, LIGHT_CIRCUITS + 1):
    #    pca.channels[i].duty_cycle = 32768  # 50% duty cycle (half brightness)
    #    time.sleep(1)  # Wait 1 second to observe
    #    pca.channels[i].duty_cycle = 0  # Turn off

    while True:
        read_switches()
        time.sleep(ADJUST_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Script terminated by KeyboardInterrupt")
    except Exception as e:
        logging.error(f"Script terminated due to error: {e}")
    finally:
        GPIO.cleanup()
        if client:
            client.loop_stop()
            client.disconnect()
        logging.info("Script terminated")