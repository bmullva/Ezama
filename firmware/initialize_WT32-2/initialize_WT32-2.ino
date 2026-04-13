#include <ETH.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <EEPROM.h>
#include <ArduinoJson.h>          // <<<<< ADD THIS LIBRARY

//https://www.ezama.tech/ez/ard/esp_number?increment=True
// Config
#define EEPROM_SIZE 512
#define DEVICE_ID_OFFSET 222
#define MQTT_BROKER_IP {192, 168, 99, 1}
#define MQTT_PORT 1883
#define REPORT_TOPIC "/system/reporting"
#define REPORT_INTERVAL 6000   // 6 seconds

// Hardcode your 8-digit ID here (change before upload!)
#define NEW_DEVICE_ID "00000087"  // Exactly 8 chars

// Globals
WiFiClient espClient;
PubSubClient mqttClient(espClient);

String deviceId = String(NEW_DEVICE_ID);
unsigned long lastReport = 0;

void connectMQTT() {
  IPAddress broker(192, 168, 99, 1);
  mqttClient.setServer(broker, MQTT_PORT);
  
  int attempts = 0;
  while (!mqttClient.connected() && attempts < 10) {
    Serial.print("Attempting MQTT connection...");
    if (mqttClient.connect("EEPROM_WRITER")) {
      Serial.println(" connected");
    } else {
      Serial.print(" failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 2s");
      delay(2000);
      attempts++;
    }
  }
}

void publishReport() {
  if (!mqttClient.connected()) {
    connectMQTT();
    if (!mqttClient.connected()) return;
  }

  StaticJsonDocument<128> doc;
  doc["device_id"] = deviceId;
  doc["ip"] = ETH.localIP().toString();

  char payload[128];
  size_t len = serializeJson(doc, payload);

  if (mqttClient.publish(REPORT_TOPIC, payload, len)) {
    Serial.println("Report published: " + String(payload));
  } else {
    Serial.println("Publish failed");
  }
}

void setup() {
  Serial.begin(115200);

  // Ethernet setup (WT32-ETH01)
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ETH.begin(ETH_PHY_LAN8720, 1, 23, 18, 16, ETH_CLOCK_GPIO0_IN);
#else
  ETH.begin(1, 16, 23, 18, ETH_PHY_LAN8720, ETH_CLOCK_GPIO0_IN);
#endif

  while (!ETH.linkUp()) {
    delay(500);
  }
  Serial.println("ETH connected: " + ETH.localIP().toString());

  // OTA
  ArduinoOTA.setHostname("EEPROM_WRITER");
  ArduinoOTA.begin();

  // Write ID to EEPROM (one-time)
  EEPROM.begin(EEPROM_SIZE);
  if (deviceId.length() != 8) {
    Serial.println("ERROR: ID must be exactly 8 chars!");
    while (true) delay(1);
  }
  for (int i = 0; i < 8; i++) {
    EEPROM.write(DEVICE_ID_OFFSET + i, deviceId.charAt(i));
  }
  EEPROM.commit();
  Serial.println("ID permanently written to EEPROM: " + deviceId);

  // Initial MQTT connection
  connectMQTT();
  publishReport();  // Send first report immediately
}

void loop() {
  ArduinoOTA.handle();

  unsigned long now = millis();
  if (now - lastReport >= REPORT_INTERVAL) {
    publishReport();
    lastReport = now;
  }

  mqttClient.loop();  // Keeps connection alive and processes incoming packets
}
