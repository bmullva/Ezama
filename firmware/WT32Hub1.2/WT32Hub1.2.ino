/*
 * Smart Lighting Controller for WT32-ETH01 ESP32 Board
 * 
 * Overview:
 * This Arduino sketch implements a wall-mounted smart lighting panel controller using an ESP32-based WT32-ETH01 board.
 * It manages up to 12 PWM-controlled LED light circuits (configurable for dual-temperature mixing on the last few pairs)
 * and 32 multiplexed push-button switches for local control. The system uses MQTT over Ethernet for remote commands,
 * status reporting, and integration with home automation systems like Node-RED. It supports OTA updates, persists
 * basic config in EEPROM, and provides debug logging via MQTT.
 * 
 * Hardware Assumptions:
 * - Board: WT32-ETH01 (ESP32 with LAN8720 Ethernet PHY).
 * - PWM Driver: Adafruit PCA9685 (16-channel, I2C at pins 14/15) for lights (uses channels 1-12; 13-16 reserved).
 * - Buttons: Two 16-channel analog muxes (e.g., CD74HC4067) for 32 active-low push-buttons.
 *   - MUX1 (buttons 0-15): Output on GPIO 5 (pull-up).
 *   - MUX2 (buttons 16-31): Output on GPIO 2 (pull-up).
 *   - Select pins: SEL0=12, SEL1=4, SEL2=32, SEL3=33 (all start low).
 * - No WiFi; Ethernet only (PHY config: MISO=16, MOSI=23, SCLK=18, CS=1, CLK=0_IN).
 * 
 * Key Features:
 * - Lights: On/off, brightness (5-100%), temperature (0=cool/6500K to 255=warm/2700K).
 *   - Dual-temp mode: Configurable (0-6 pairs); odd lights control blend (even channels ignored for commands).
 * - Buttons: Debounced (50ms), with state machine for short-click (toggle on/off), long-hold (brighten/dim),
 *   and click+quick-hold (heat/cool). Buttons paired 2:1 (e.g., 0/1 → switch S1 → light L1).
 * - MQTT: Broker at 192.168.99.1:1883 (no auth). Dynamic topics based on DEVICE_ID (default "WT321").
 *   - Subscribes:
 *     - /lights/{DEVICE_ID}/+/command (e.g., JSON state or legacy "on", "off", "click", "set_brightness 50", "set_temperature 128").
 *     - /lights/{DEVICE_ID}/dual/command (sets DUAL_TEMP_LIGHTS 0-6).
 *     - /system/broadcast (for "ping" to trigger report).
 *   - Publishes:
 *     - /switches/{DEVICE_ID}/S{1-16}/action (button actions: "on", "off", "start_brighten", etc.).
 *     - /system/reporting (JSON on ping: {device_id, version, ip, lights:{count,dual_temp}, switches:16, sensors:[]}).
 *     - /system/debug (logs: connections, commands, presses, errors).
 * - Persistence: EEPROM (512 bytes) stores DEVICE_ID (offset 222, 8 alnum chars) and DUAL_TEMP_LIGHTS (offset 220).
 * - Boot Behavior: Initializes lights off at 100% brightness/0 temp. No boot light test (to preserve retained MQTT states).
 * - Loop: OTA handle, MQTT maintain/process, button scan (~50ms).
 * 
 * Integration Notes:
 * - For Node-RED: Use retained MQTT OUT on command topics to restore states post-reboot (device resubscribes and applies).
 * - Debug: Subscribe to /system/debug for logs.
 * - Version: 1.0 (Ethernet tweaks for ESP32 Arduino core v3+).
 * - Limitations: Fixed broker IP; no MQTT auth; basic error handling (constrains values).
 * 
 * Author: [Your Name/Generated]
 * Date: November 2025
 * License: MIT (or as appropriate)
 */

#include <ETH.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <ArduinoJson.h>
#include <EEPROM.h>  // Added for EEPROM
#include <ctype.h>   // For isalnum()

// Config
#define VERSION "1.2"
const int LIGHT_CIRCUITS = 12;
const int SWITCHES = 16;
#define MQTT_PORT 1883
#define MQTT_BROADCAST "/system/broadcast"
#define MQTT_REPORTING "/system/reporting"
#define MQTT_DEBUG "/system/debug"
#define DEFAULT_DEVICE_ID "WT321"

// Pins (adjusted for safe GPIOs)
#define SDA_PIN 14
#define SCL_PIN 15
#define SEL0_PIN 12  // MUX SEL0 (changed from 17)
#define SEL1_PIN 4   // MUX SEL1
#define SEL2_PIN 32  // MUX SEL2 (CFG)
#define SEL3_PIN 33  // MUX SEL3 (485_EN)
#define MUX1_PIN 5   // MUX1 output (buttons 0-15)
#define MUX2_PIN 2   // MUX2 output (buttons 16-31)

// Constants
#define DEBOUNCE_TIME 50UL
#define ACTION_THRESHOLD 400UL
#define CLICK_HOLD_WINDOW 500UL
#define ADJUST_INTERVAL 50UL
#define MAX_LIGHTS 13
#define MAX_BUTTONS 32
#define EEPROM_SIZE 512
#define DEVICE_ID_OFFSET 222
#define DUAL_TEMP_OFFSET 220

// States
enum ButtonState { IDLE = 0, PRESSED = 1, CLICKED = 2, HOLDING = 3 };

// Globals
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();
WiFiClient espClient;
PubSubClient mqttClient(espClient);
const char* broadcastTopic = MQTT_BROADCAST;

// Dynamic config
String DEVICE_ID;
int DUAL_TEMP_LIGHTS;
String lightTopic;
String dualCommandTopic;

// Light states
byte onOff[MAX_LIGHTS] = {0};
int brightness[MAX_LIGHTS] = {0};
byte temperature[MAX_LIGHTS] = {0};

// Button states
ButtonState buttonState[MAX_BUTTONS] = {IDLE};
unsigned long pressStart[MAX_BUTTONS] = {0};
unsigned long lastDebounceTime[MAX_BUTTONS] = {0};
int lastReading[MAX_BUTTONS] = {1};
int dPinReading[MAX_BUTTONS] = {1};
unsigned long lastClickTime[MAX_BUTTONS] = {0};

void debugPublish(const String& msg) {
  if (mqttClient.connected()) {
    mqttClient.publish(MQTT_DEBUG, msg.c_str());
  }
}

void WiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      debugPublish("ETH Started");
      ETH.setHostname(DEVICE_ID.c_str());  // Use dynamic DEVICE_ID
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      debugPublish("ETH Connected");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      debugPublish("ETH MAC: " + ETH.macAddress() + ", IPv4: " + ETH.localIP().toString() + (ETH.fullDuplex() ? ", FULL_DUPLEX" : "") + ", " + String(ETH.linkSpeed()) + "Mbps");
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      debugPublish("ETH Disconnected");
      break;
    case ARDUINO_EVENT_ETH_STOP:
      debugPublish("ETH Stopped");
      break;
    default:
      break;
  }
}

void setup() {
  // Read from EEPROM
  EEPROM.begin(EEPROM_SIZE);
  char device_id[9];
  for (int i = 0; i < 8; i++) {
    device_id[i] = char(EEPROM.read(DEVICE_ID_OFFSET + i));
  }
  device_id[8] = '\0';
  DEVICE_ID = String(device_id);

  // Validate and fallback if invalid (empty, too short/long, or non-alphanumeric)
  bool valid = true;
  if (DEVICE_ID.length() < 1 || DEVICE_ID.length() > 8) {
    valid = false;
  } else {
    for (size_t j = 0; j < DEVICE_ID.length(); j++) {
      if (!isalnum(DEVICE_ID.charAt(j))) {
        valid = false;
        break;
      }
    }
  }

  if (!valid) {
    debugPublish("Invalid DEVICE_ID from EEPROM, falling back to default");
    DEVICE_ID = DEFAULT_DEVICE_ID;
    // Optional: Write default to EEPROM for persistence
    for (int i = 0; i < 8; i++) {
      EEPROM.write(DEVICE_ID_OFFSET + i, DEVICE_ID.charAt(i));
    }
    EEPROM.commit();
  }

  int dual_temp_raw = EEPROM.read(DUAL_TEMP_OFFSET);
  DUAL_TEMP_LIGHTS = constrain(dual_temp_raw, 0, 6);

  debugPublish("Loaded DEVICE_ID: " + DEVICE_ID + ", DUAL_TEMP_LIGHTS: " + String(DUAL_TEMP_LIGHTS));

  WiFi.mode(WIFI_OFF);
  WiFi.onEvent(WiFiEvent);

  // ETH begin (corrected for WT32-ETH01)
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ETH.begin(ETH_PHY_LAN8720, 1, 23, 18, 16, ETH_CLOCK_GPIO0_IN);
#else
  ETH.begin(1, 16, 23, 18, ETH_PHY_LAN8720, ETH_CLOCK_GPIO0_IN);
#endif

  debugPublish("Connecting to ETH...");
  while (!ETH.linkUp()) {
    delay(500);
  }
  debugPublish("ETH connected");

  // Set dynamic topics
  lightTopic = "/lights/" + DEVICE_ID + "/+/command";
  dualCommandTopic = "/lights/" + DEVICE_ID + "/dual/command";

  // OTA setup
  ArduinoOTA.setHostname(DEVICE_ID.c_str());
  ArduinoOTA.begin();

  // GPIO setup
  pinMode(SEL0_PIN, OUTPUT);
  pinMode(SEL1_PIN, OUTPUT);
  pinMode(SEL2_PIN, OUTPUT);
  pinMode(SEL3_PIN, OUTPUT);
  digitalWrite(SEL0_PIN, LOW);
  digitalWrite(SEL1_PIN, LOW);
  digitalWrite(SEL2_PIN, LOW);
  digitalWrite(SEL3_PIN, LOW);

  pinMode(MUX1_PIN, INPUT_PULLUP);
  pinMode(MUX2_PIN, INPUT_PULLUP);

  // I2C and PWM setup
  Wire.begin(SDA_PIN, SCL_PIN);
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(1000);
  for (int ch = 0; ch < 16; ch++) {
    pwm.setPWM(ch, 0, 0);
  }

  // Light init
  for (int i = 1; i <= LIGHT_CIRCUITS; i++) {
    onOff[i] = 0;
    brightness[i] = 100;
    temperature[i] = 0;
  }

  // MQTT setup
  IPAddress broker(192, 168, 99, 1);
  mqttClient.setServer(broker, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  connect_mqtt();

  // Boot light test removed to preserve retained MQTT states from Node-RED (e.g., post-reboot restoration).
  // Lights start off; MQTT commands will apply shortly after connect.
}

void loop() {
  ArduinoOTA.handle();

  if (!mqttClient.connected()) {
    connect_mqtt();
  }
  mqttClient.loop();

  read_switches();
  delay(ADJUST_INTERVAL);
}

void connect_mqtt() {
  IPAddress broker(192, 168, 99, 1);
  while (!mqttClient.connected()) {
    debugPublish("Attempting MQTT connection...");
    String clientId = DEVICE_ID + "-" + String(random(0xffff), HEX);
    debugPublish("Client ID: " + clientId);
    if (mqttClient.connect(clientId.c_str())) {
      debugPublish("MQTT connected");
      debugPublish("Subscribing to lightTopic: " + lightTopic);
      mqttClient.subscribe(lightTopic.c_str());
      mqttClient.subscribe(dualCommandTopic.c_str());
      mqttClient.subscribe(broadcastTopic);
    } else {
      debugPublish("MQTT failed, rc=" + String(mqttClient.state()) + " try again in 5s");
      delay(5000);
    }
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msgTopic(topic);
  String payloadStr = "";
  for (unsigned int i = 0; i < length; i++) {
    payloadStr += (char)payload[i];
  }
  debugPublish("Received on " + msgTopic + ": " + payloadStr);

  // Handle dual temp update
  if (msgTopic.equals(dualCommandTopic)) {
    int new_dual = payloadStr.toInt();
    new_dual = constrain(new_dual, 0, 6);
    if (new_dual != DUAL_TEMP_LIGHTS) {
      DUAL_TEMP_LIGHTS = new_dual;
      EEPROM.write(DUAL_TEMP_OFFSET, DUAL_TEMP_LIGHTS);
      EEPROM.commit();
      debugPublish("Updated DUAL_TEMP_LIGHTS to " + String(DUAL_TEMP_LIGHTS));
    }
    return;
  }

  if (msgTopic.equals(broadcastTopic) && payloadStr.equals("ping")) {
    send_ping_response();
    return;
  }

  if (msgTopic.startsWith("/lights/" + DEVICE_ID + "/")) {
    // Extract light_id from /lights/WT321/L1/command -> L1
    int lPos = msgTopic.indexOf("/L", 8);  // after /lights/ID/
    if (lPos != -1) {
      int cmdPos = msgTopic.indexOf("/command", lPos);
      if (cmdPos != -1) {
        String lStr = msgTopic.substring(lPos + 1, cmdPos);
        if (lStr.startsWith("L") && lStr.length() > 1) {
          int light_id = lStr.substring(1).toInt();
          if (light_id >= 1 && light_id <= LIGHT_CIRCUITS) {
            handle_light_command(light_id, payloadStr);
          }
        }
      }
    }
  }
}

void send_ping_response() {
  StaticJsonDocument<256> doc;
  doc["device_id"] = DEVICE_ID;
  doc["version"] = VERSION;
  doc["ip"] = ETH.localIP().toString();

  JsonObject lights_obj = doc.createNestedObject("lights");
  lights_obj["count"] = LIGHT_CIRCUITS;
  lights_obj["dual_temp"] = DUAL_TEMP_LIGHTS;

  doc["switches"] = SWITCHES;
  JsonArray sensors = doc.createNestedArray("sensors");  // Empty array

  String jsonStr;
  serializeJson(doc, jsonStr);
  mqttClient.publish(MQTT_REPORTING, jsonStr.c_str());
  debugPublish("Ping response sent");
}

void handle_light_command(int light_id, String command) {
  if (light_id < 1 || light_id > LIGHT_CIRCUITS) return;

  int start_dual = max(1, LIGHT_CIRCUITS + 1 - 2 * DUAL_TEMP_LIGHTS);
  if (light_id % 2 == 0 && light_id >= start_dual) {
    debugPublish("Ignore command to even dual light " + String(light_id));
    return;
  }

  debugPublish("Command for L" + String(light_id) + ": " + command);

  // New: Check for JSON payload (atomic update)
  DynamicJsonDocument doc(256);
  DeserializationError error = deserializeJson(doc, command);
  if (!error) {
    onOff[light_id] = (doc["on_off"] == "on") ? 1 : 0;
    brightness[light_id] = constrain(doc["brightness"] | 100, 5, 100);
    if (is_dual_temp(light_id)) {
      temperature[light_id] = constrain(doc["temperature"] | 0, 0, 255);
    }
    debugPublish("Atomic JSON update for L" + String(light_id));
  } else {
    // Fallback: Legacy string parsing
    if (command == "on") {
      onOff[light_id] = 1;
    } else if (command == "off") {
      onOff[light_id] = 0;
    } else if (command == "click") {
      onOff[light_id] = 1 - onOff[light_id];
    } else if (command.startsWith("set_brightness ")) {
      int val = command.substring(15).toInt();
      brightness[light_id] = constrain(val, 5, 100);
    } else if (command.startsWith("set_temperature ")) {
      int val = command.substring(15).toInt();
      temperature[light_id] = constrain(val, 0, 255);
    }
    // No continuous handling - removed
  }

  update_light_pwm(light_id);
}

void update_light_pwm(int light_id) {
  int max_duty = 4095;  // 12-bit
  if (is_dual_temp(light_id)) {
    float b_frac = brightness[light_id] / 100.0;
    float t_frac = temperature[light_id] / 255.0;
    int duty1 = int(onOff[light_id] * b_frac * t_frac * max_duty);  // 6500K
    int duty2 = int(onOff[light_id] * b_frac * (1.0 - t_frac) * max_duty);  // 2700K
    pwm.setPWM(light_id, 0, duty2);
    pwm.setPWM(light_id + 1, 0, duty1);
    debugPublish("Dual L" + String(light_id) + ": duty1=" + String(duty1) + ", duty2=" + String(duty2));
  } else {
    int duty = int(onOff[light_id] * (brightness[light_id] / 100.0) * max_duty);
    pwm.setPWM(light_id, 0, duty);
    debugPublish("Single L" + String(light_id) + ": duty=" + String(duty));
  }
}

bool is_dual_temp(int light_id) {
  int start_dual = max(1, LIGHT_CIRCUITS + 1 - 2 * DUAL_TEMP_LIGHTS);
  return (light_id >= start_dual && light_id % 2 == 1);
}

void set_mux_channel(int channel) {
  digitalWrite(SEL0_PIN, (channel & 1) ? HIGH : LOW);
  digitalWrite(SEL1_PIN, (channel & 2) ? HIGH : LOW);
  digitalWrite(SEL2_PIN, (channel & 4) ? HIGH : LOW);
  digitalWrite(SEL3_PIN, (channel & 8) ? HIGH : LOW);
}

void read_switches() {
  for (int i = 0; i < 16; i++) {
    set_mux_channel(i);
    delayMicroseconds(50);
    int mux1_reading = digitalRead(MUX1_PIN);
    int mux2_reading = digitalRead(MUX2_PIN);
    update_button_state(i, mux1_reading);
    update_button_state(i + 16, mux2_reading);
  }
}

void update_button_state(int button_id, int current_reading) {
  unsigned long now = millis();

  // Debounce
  if (current_reading != lastReading[button_id]) {
    lastDebounceTime[button_id] = now;
    lastReading[button_id] = current_reading;
  }

  if ((now - lastDebounceTime[button_id]) > DEBOUNCE_TIME) {
    if (current_reading != dPinReading[button_id]) {
      dPinReading[button_id] = current_reading;
      if (current_reading == LOW) {  // Pressed (active low)
        debugPublish("Button " + String(button_id) + " pressed");
        if (buttonState[button_id] == IDLE) {
          buttonState[button_id] = PRESSED;
          pressStart[button_id] = now;
        } else if (buttonState[button_id] == CLICKED && (now - lastClickTime[button_id]) < CLICK_HOLD_WINDOW) {
          buttonState[button_id] = HOLDING;
          String action = (button_id % 2 == 0) ? "start_cool" : "start_heat";
          publish_switch_action(button_id, action);
        }
      } else {  // Released
        unsigned long press_duration = now - pressStart[button_id];
        debugPublish("Button " + String(button_id) + " released, duration=" + String(press_duration / 1000.0, 3) + "s");
        if (buttonState[button_id] == PRESSED && press_duration < ACTION_THRESHOLD) {
          buttonState[button_id] = CLICKED;
          lastClickTime[button_id] = now;
        } else if (buttonState[button_id] == PRESSED || buttonState[button_id] == HOLDING) {
          publish_switch_action(button_id, "stop");
          buttonState[button_id] = IDLE;
        }
      }
    }

    // CLICKED timeout
    if (buttonState[button_id] == CLICKED && (now - lastClickTime[button_id]) >= CLICK_HOLD_WINDOW) {
      String action = (button_id % 2 == 0) ? "off" : "on";
      publish_switch_action(button_id, action);
      buttonState[button_id] = IDLE;
    }

    // Hold detection
    if (buttonState[button_id] == PRESSED && (now - pressStart[button_id]) >= ACTION_THRESHOLD) {
      buttonState[button_id] = HOLDING;
      String action = (button_id % 2 == 0) ? "start_dim" : "start_brighten";
      publish_switch_action(button_id, action);
    }
  }
}

void publish_switch_action(int button_id, String action) {
  int switch_id = (button_id / 2) + 1;
  String topic = "/switches/" + DEVICE_ID + "/S" + String(switch_id) + "/action";
  mqttClient.publish(topic.c_str(), action.c_str());
  debugPublish("Published: " + topic + " - " + action);
}
