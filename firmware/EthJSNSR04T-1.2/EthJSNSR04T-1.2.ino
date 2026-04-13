#include <ETH.h>         
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>   

WiFiClient ethClient;
PubSubClient mqttClient(ethClient);

const char* mqtt_server {};
char mqtt_ip_1[] = "192.168.99.1";
char mqtt_ip_2[] = "192.168.99.10";
char mqtt_ip_3[] = "192.168.6.97";
char device_id[9] = {};
const int mqtt_port = 1883;
const char* mqtt_topic_subscribe = "/system/broadcast";
const char* mqtt_topic_publish = "/system/reporting";
static bool eth_connected = false;
const int password_length_addr = 231;
const int password_addr = 240;

#define TRIG_PIN 32
#define ECHO_PIN 33
#define TANK_HEIGHT 200  // Total tank height in cm (only used for reference/max range)

String type_ = "Ethernet JSN-SR04T Water Level";
String ver = "1.1";  // Updated version

// Measurement variables
float distance_to_water = 0.0;   // This is what we now report: sensor → water surface (cm)
bool sensor_ok = false;

// Debug globals
long duration = 0;
int test_phase = 0;
unsigned long last_debug = 0;
const unsigned long debug_interval = 5000;

// Interrupt globals
volatile unsigned long pulse_start = 0;
volatile unsigned long pulse_end = 0;
volatile bool pulse_ready = false;
bool interrupt_attached = false;

// ISR
void IRAM_ATTR echo_isr() {
  unsigned long now = micros();
  if (digitalRead(ECHO_PIN) == HIGH) {
    pulse_start = now;
  } else if (pulse_start > 0 && now > pulse_start) {
    pulse_end = now;
    duration = pulse_end - pulse_start;
    pulse_ready = true;
  }
}

// Single pulse read (20µs trigger for JSN-SR04T v2/v3)
long read_pulse() {
  pulse_start = 0;
  pulse_end = 0;
  pulse_ready = false;

  digitalWrite(TRIG_PIN, LOW); delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(20);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long timeout_start = millis();
  while (!pulse_ready && (millis() - timeout_start < 50)) {
    delayMicroseconds(10);
  }

  long min_dur = (test_phase == 3) ? 10 : 100;  // Loopback allows shorter pulses
  if (!pulse_ready || duration < min_dur || duration > 40000 || duration <= 0) {
    duration = 0;
  }
  return duration;
}

// Average 3 readings for stability
long average_pulse() {
  long d1 = read_pulse(); delay(50);
  long d2 = read_pulse(); delay(50);
  long d3 = read_pulse();
  return (d1 + d2 + d3) / 3;
}

// PUBLISH NORMAL REPORTING (every ~6s via ezama_loop)
void publish_reporting_json() {
  DynamicJsonDocument state_json(1024);
  state_json["device_id"] = device_id;
  state_json["version"] = ver;
  state_json["ip"] = ETH.localIP();
  state_json["lights"] = "";
  state_json["switches"] = "";

  JsonArray sensors = state_json.createNestedArray("sensors");
  JsonObject sensor = sensors.createNestedObject();
  sensor["type"] = "jsn-sr04t";
  JsonArray fields = sensor.createNestedArray("fields");
  JsonObject field1 = fields.createNestedObject();

  // CHANGED: Now reports distance from sensor to water surface
  field1["name"] = "distance_to_water_cm";   // Clear and accurate
  field1["unit"] = "cm";
  field1["display_type"] = "gauge";
  JsonObject range1 = field1.createNestedObject("range");
  range1["min"] = 20;                        // JSN-SR04T reliable from ~20cm
  range1["max"] = TANK_HEIGHT + 100;         // Allow readings above empty tank

  String output;
  serializeJson(state_json, output);
  mqttClient.publish("/system/reporting", output.c_str());

  // Raw numeric topic (for graphs, Home Assistant, Node-RED, etc.)
  char value_str[10];
  if (distance_to_water > 0 && distance_to_water <= 700)
    dtostrf(distance_to_water, 4, 1, value_str);
  else
    strcpy(value_str, "-1");

  mqttClient.publish(("/sensors/" + String(device_id) + "/jsn-sr04t/data").c_str(), value_str);
}

void receive_controls_json(String topic, String messageTemp) {
  // Not used
}

void publish_controls_json(String pin_name, String pin_msg) {
  // Not used
}

// Debug publishing
void publish_debug_json(String phase_name, String details) {
  if (!eth_connected) return;

  DynamicJsonDocument debug_json(768);
  debug_json["device_id"] = device_id;
  debug_json["phase"] = phase_name;
  debug_json["details"] = details;
  debug_json["gpio32_state"] = digitalRead(TRIG_PIN);
  debug_json["gpio33_state"] = digitalRead(ECHO_PIN);
  debug_json["duration_us"] = duration;
  debug_json["distance_to_water_cm"] = (distance_to_water > 0 && distance_to_water < 1000) ? String(distance_to_water, 1) : "invalid";
  debug_json["valid_read"] = (duration > 0 && duration <= 40000);

  String output;
  serializeJson(debug_json, output);
  String debug_topic = "/debug/" + String(device_id) + "/test";
  mqttClient.publish(debug_topic.c_str(), output.c_str());
}

void setup() {
  EEPROM.begin(512);
  ezama_setup();
  mqttClient.setBufferSize(1024);
  mqttClient.subscribe("/system/broadcast");
  delay(2000);

  pinMode(TRIG_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  pinMode(ECHO_PIN, INPUT);  // External voltage divider provides pulldown

  sensor_ok = true;
  test_phase = 0;
  last_debug = millis() - debug_interval;  // Force first debug immediately
  interrupt_attached = false;
}

void loop() {
  ezama_loop();
  ArduinoOTA.handle();

  unsigned long now = millis();
  if (now - last_debug >= debug_interval) {
    String phase_name, details;

    // Attach interrupt only when needed
    if (!interrupt_attached && test_phase >= 3) {
      attachInterrupt(digitalPinToInterrupt(ECHO_PIN), echo_isr, CHANGE);
      interrupt_attached = true;
    }

    switch (test_phase) {
      case 0:  // GPIO32 output test
        digitalWrite(TRIG_PIN, !digitalRead(TRIG_PIN));
        phase_name = "GPIO32_Output";
        details = digitalRead(TRIG_PIN) ? "HIGH (3.3V)" : "LOW (0V)";
        if (now > 20000) test_phase = 1;
        break;

      case 1:  // GPIO33 pulled to GND
        phase_name = "GPIO33_Input_GND";
        details = "Jumper 33 to GND → expect state 0";
        if (now > 25000) { test_phase = 2; digitalWrite(TRIG_PIN, LOW); }
        break;

      case 2:  // GPIO33 pulled to 3.3V
        phase_name = "GPIO33_Input_3V3";
        details = "Jumper 33 to 3.3V → expect state 1";
        if (now > 30000) { test_phase = 3; digitalWrite(TRIG_PIN, LOW); }
        break;

      case 3:  // Loopback test (32 to 33)
        phase_name = "Loopback_Single";
        duration = average_pulse();
        if (duration > 10 && duration < 50) {
          details = "PASS: Loopback ~20–40µs detected";
        } else {
          details = "FAIL: duration=" + String(duration) + "µs (check jumper)";
        }
        if (now > 40000) test_phase = 4;
        break;

      default:  // Normal operation: measure distance to water
        phase_name = "Sensor_Operational";
        if (sensor_ok) {
          duration = average_pulse();
          distance_to_water = (duration > 0) ? (duration * 0.0343 / 2.0) : 0.0;

          if (duration == 0) {
            distance_to_water = -1;
            details = "No echo received";
          }
          else if (distance_to_water < 20 || distance_to_water > 700) {
            distance_to_water = -1;
            details = "Out of range: " + String(distance_to_water, 1) + " cm";
          }
          else {
            details = "OK → Distance to water = " + String(distance_to_water, 1) + " cm";
          }
        } else {
          details = "Sensor offline";
        }
        break;
    }

    publish_debug_json(phase_name, details);
    last_debug = now;
  }

  // Detach interrupt when not measuring
  if (test_phase < 3 && interrupt_attached) {
    detachInterrupt(digitalPinToInterrupt(ECHO_PIN));
    interrupt_attached = false;
  }

  // Fallback reporting if sensor fails long-term
  if (eth_connected && !sensor_ok) {
    static unsigned long fallback_pub = 0;
    if (millis() - fallback_pub >= 30000) {
      DynamicJsonDocument fallback_json(512);
      fallback_json["device_id"] = device_id;
      fallback_json["version"] = ver;
      fallback_json["ip"] = ETH.localIP();
      fallback_json["sensors"] = "jsn-sr04t offline";
      String output;
      serializeJson(fallback_json, output);
      mqttClient.publish("/system/reporting", output.c_str());
      fallback_pub = millis();
    }
  }

  delay(1000);
}
