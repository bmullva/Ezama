#include <ETH.h>          // For WT32-ETH01
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>   // Add ArduinoOTA for OTA updates
#include <OneWire.h>
#include <DallasTemperature.h>

WiFiClient ethClient;
PubSubClient mqttClient(ethClient);
const char* mqtt_server {};
char mqtt_ip_1[] = "192.168.99.1";
char mqtt_ip_2[] = "192.168.99.10";
char mqtt_ip_3[] = "192.168.6.97";
char device_id[9] = {};
const int mqtt_port = 1883;
const char* mqtt_topic_subscribe = "/system/broadcast"; // Corrected to match EthMomentary
const char* mqtt_topic_publish = "/system/reporting";  // Corrected to match EthMomentary
static bool eth_connected = false;
const int password_length_addr = 231; // 8 <= len <= 63
const int password_addr = 240; // 8-63 byte (240-302)

// 1 INITIALIZE DEVICE PARTICULAR CONSTANTS & VARIABLES
String type_ = "Ethernet DS18B20 Temperature";
String ver = "1.2.1";

#define ONE_WIRE_BUS 33
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
float tempC {};
float tempF {};

// 2 REPORT (SENT EVERY 6 SECONDS)
void publish_reporting_json() {
  String output;
  DynamicJsonDocument state_json(1024);
  char sj[1024];
  String topic = "/system/reporting";
  state_json["device_id"] = device_id;
  state_json["version"] = ver;
  state_json["ip"] = ETH.localIP();
  state_json.createNestedObject("lights");
  state_json.createNestedObject("switches");
  JsonArray sensors = state_json.createNestedArray("sensors");
  JsonObject sensor = sensors.createNestedObject();
  sensor["type"] = "DS18B20";
  sensor["fields"][0]["name"] = "temperature_c";
  sensor["fields"][0]["unit"] = "C";
  sensor["fields"][0]["display_type"] = "gauge";
  sensor["fields"][0]["range"]["min"] = -55;
  sensor["fields"][0]["range"]["max"] = 125;
  serializeJson(state_json, output);
  output.toCharArray(sj, 1024);
  mqttClient.publish(topic.c_str(), sj);

  // Publish individual sensor readings
  topic = "/sensors/" + String(device_id) + "/DS18B20/data";
  mqttClient.publish(topic.c_str(), String(tempC).c_str());

  topic = String(device_id) + "/tempF";
//  mqttClient.publish(topic.c_str(), String(tempF).c_str());
}

// 3 REPORT ID: "mqtt_pub -h XXX.XXX.XXX.XXX -m ids -t broadcast"
// Reserved

// 4 RECEIVE CONTROLS (to this exact device, from callback)
void receive_controls_json(String topic, String msg) {
  if (topic == "/system/broadcast" && msg == "ping") {
    String output;
    DynamicJsonDocument state_json(256);
    state_json["device_id"] = device_id;
    state_json["version"] = ver;
    state_json["ip"] = ETH.localIP().toString();
    JsonObject lights = state_json.createNestedObject("lights");
    JsonObject switches = state_json.createNestedObject("switches");
    JsonArray sensors = state_json.createNestedArray("sensors");
    JsonObject sensor = sensors.createNestedObject();
    sensor["type"] = "ds18b20";
    JsonArray fields = sensor.createNestedArray("fields");
    JsonObject field = fields.createNestedObject();
    field["name"] = "temperature_c";
    field["unit"] = "°C";
    field["display_type"] = "gauge";
    JsonObject range = field.createNestedObject("range");
    range["min"] = -55;
    range["max"] = 125;
    serializeJson(state_json, output);
    String topic_report = "/system/reporting";
    mqttClient.publish(topic_report.c_str(), output.c_str());
    return;
  }

  // Add specific controls if needed
}

// 5 SEND CONTROLS (publish_controls only if controller module)
void publish_controls_json(String pin_name, String pin_msg) {
  // Not used for DS18B20, but kept for consistency
}

// 6 SETUP (pins)
void specific_connect() {
  // No additional MQTT subscriptions needed for DS18B20
}

void setup() {
  Serial.begin(115200);
  ezama_setup(); // From ezama.ino
  mqttClient.subscribe("/system/broadcast");
  specific_connect();
  sensors.begin(); // Initialize DS18B20 sensor
  pinMode(ONE_WIRE_BUS, INPUT_PULLUP);
}

// 7 MAIN LOOP
void loop() {
  ezama_loop();        // MQTT and app logic from ezama.ino
  ArduinoOTA.handle(); // Handle OTA updates

  if (eth_connected) {
    // Read DS18B20 sensor
    sensors.requestTemperatures(); // Send command to get temperatures
    tempC = sensors.getTempCByIndex(0);
    tempF = sensors.getTempFByIndex(0);

    // Check for valid temperature readings
    if (tempC == DEVICE_DISCONNECTED_C) {
      Serial.println("Error: DS18B20 disconnected or failed to read");
      return;
    }

    // Publish sensor data every 6 seconds
    static unsigned long lastPublish = 0;
    if (millis() - lastPublish >= 6000) {
      publish_reporting_json();
      lastPublish = millis();
    }
  }

  delay(100); // Small delay to prevent tight looping
}
