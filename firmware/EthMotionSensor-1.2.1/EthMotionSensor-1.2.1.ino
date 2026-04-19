#include <ETH.h>          // For WT32-ETH01
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>   // Add ArduinoOTA for OTA updates

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
String type_ = "Ethernet RCWL-0516 Motion";
String ver = "1.2.1";

const int motionPin = 12; // RCWL-0516 connected to GPIO12
String onOff = "off";

// 2 REPORT (SENT EVERY 6 SECONDS)
void publish_reporting_json() {
  String output;
  DynamicJsonDocument state_json(1024);
  char sj[1024];
  String topic = "/system/reporting";
  state_json["device_id"] = device_id;
  state_json["version"] = ver;
  state_json["ip"] = ETH.localIP();
  state_json["lights"] = "";
  state_json["switches"] = 1;
  JsonArray sensors = state_json.createNestedArray("sensors");
  serializeJson(state_json, output);
  output.toCharArray(sj, 1024);
  mqttClient.publish(topic.c_str(), sj);

  // Publish motion state
  topic = "/switches/" + String(device_id) + "/S1/action";
  mqttClient.publish(topic.c_str(), onOff.c_str());
}

// 3 REPORT ID: "mqtt_pub -h XXX.XXX.XXX.XXX -m ids -t broadcast"
// Reserved

// 4 RECEIVE CONTROLS (to this exact device, from callback)
void receive_controls_json(String topic, String msg) {
  // Add specific controls if needed
}

// 5 SEND CONTROLS (publish_controls only if controller module)
void publish_controls_json(String pin_name, String pin_msg) {
  // Not used for RCWL-0516, but kept for consistency
}

// 6 SETUP (pins)
void specific_connect() {
  // No additional MQTT subscriptions needed for RCWL-0516
}

void setup() {
  Serial.begin(115200);
  ezama_setup(); // From ezama.ino
  specific_connect();
  pinMode(motionPin, INPUT); // Configure GPIO12 for RCWL-0516
}

// 7 MAIN LOOP
void loop() {
  ezama_loop();        // MQTT and app logic from ezama.ino
  ArduinoOTA.handle(); // Handle OTA updates

  if (eth_connected) {
    // Read RCWL-0516 motion sensor
    int currentState = digitalRead(motionPin);
    static int lastState = LOW;
    static unsigned long lastPublish = 0;

    // Detect state change
    if (currentState != lastState) {
      onOff = (currentState == HIGH) ? "on" : "off";
      //String topic = String(device_id) + "/onOff0";
      String topic = "/switches/" + String(device_id) + "/S1/action";
      mqttClient.publish(topic.c_str(), onOff.c_str());
      Serial.print("Motion state changed to: ");
      Serial.println(onOff);
      lastState = currentState;
    }

    // Publish full state every 6 seconds
    if (millis() - lastPublish >= 6000) {
      String topic = "/switches/" + String(device_id) + "/S1/action";
      mqttClient.publish(topic.c_str(), onOff.c_str());
      lastPublish = millis();
    }
  }

  delay(100); // Small delay to prevent tight looping
}
