#include <ETH.h>          //For WT32-ETH01
#include <WiFiClient.h>  //python3 ~/espota/espota.py -i 192.168.99.184 -p 3232 --auth=otapassword -f EthMomentary-1.0.ino.wt32-eth01.bin
#include <PubSubClient.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>   // Add ArduinoOTA library for OTA updates

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
//const int device_id_addr = 222; 
//8 digit (222-229) device_id
const int password_length_addr = 231; // 8 <= len <= 63
// 232-239 NOT USED
const int password_addr = 240; // 8-63 byte (240-302)


const double dVCC = 3.3;             // NodeMCU on board 3.3v vcc
const double dR2 = 10000;            // 10k ohm series resistor
const double dAdcResolution = 4095;  // 12-bit adc

const double dA = 0.001129148;       // thermistor equation parameters
const double dB = 0.000234125;
const double dC = 0.0000000876741; 

double dVout, dRth, dTemperature, dAdcValue;
int setpoint {};

// 1 INITIALIZE DEVICE PARTICULAR CONSTANTS & VARIABLES
String type_ = "Ethernet 10K NTC";
String ver = "1.2";


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
  state_json["switches"] = "";
  JsonArray sensors = state_json.createNestedArray("sensors");
  JsonObject sensor = sensors.createNestedObject();
  sensor["type"] = "ntc";
  sensor["fields"][0]["name"] = "temperature_c";
  sensor["fields"][0]["unit"] = "C";
  sensor["fields"][0]["display_type"] = "gauge";
  sensor["fields"][0]["range"]["min"] = -10;
  sensor["fields"][0]["range"]["max"] = 100;
  serializeJson(state_json, output);
  output.toCharArray(sj, 1024);
  mqttClient.publish(topic.c_str(), sj);

  topic = "/sensors/" + String(device_id) + "/ntc/data";  
  mqttClient.publish(topic.c_str(), String(dTemperature).c_str());
  //mqttClient.publish(topic.c_str(), ("dAdcValue "+String(dAdcValue)).c_str());
  //mqttClient.publish(topic.c_str(), ("dVout "+String(dVout)).c_str());
  //mqttClient.publish(topic.c_str(), ("dRth "+String(dRth)).c_str());

  topic = String(device_id)+"/setpoint";  
//  mqttClient.publish(topic.c_str(), String(setpoint).c_str());
  
}


// 3 REPORT ID: "mqtt_pub -h XXX.XXX.XXX.XXX -m ids -t broadcast"
//Reserve


// 4 RECEIVE CONTROLS (to this exact device, from callback)
void receive_controls_json(String topic, String msg) {
  if (topic == String(device_id) + "/" + String("set_temp1")) {
    setpoint = msg.toInt();
    if (setpoint != EEPROM.read(220)) {
      EEPROM.write(220, setpoint);
      EEPROM.commit();
    }
  }
}


// 5 SEND CONTROLS SEND CONTROLS (publish_controls only if controller module)
// No controls to be sent.
void publish_controls_json(String pin_name, String pin_msg) {
  String topic = String(device_id) + "/1";
  mqttClient.publish(topic.c_str(), pin_msg.c_str());
}


//6 SETUP (pins)
void specific_connect() {

}

void setup() { 
  Serial.begin(115200);
  EEPROM.begin(512);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  ezama_setup();  //in ezama8.h
  mqttClient.subscribe((String(device_id) + String("/set_temp1")).c_str());
  mqttClient.subscribe("/system/broadcast");
  setpoint = EEPROM.read(220);
}


//7 MAIN LOOP
void loop() {
  ezama_loop();  // Call a function named ezama_loop from ezama.h
  ArduinoOTA.handle(); // must be called often for OTA to work

  if (eth_connected) {
  dAdcValue = analogRead(36);
  dVout = (dAdcValue * dVCC) / dAdcResolution;
  dRth = (dVCC * dR2 / dVout) - dR2;

  //  Steinhart-Hart Thermistor Equation:
  //  Temperature in Kelvin = 1 / (A + B[ln(R)] + C[ln(R)]^3)
  //  where A = 0.001129148, B = 0.000234125 and C = 8.76741*10^-8
  // Temperature in kelvin
  dTemperature = (1 / (dA + (dB * log(dRth)) 
    + (dC * pow((log(dRth)), 3))));   

  // Temperature in degree celsius
  dTemperature = dTemperature - 273.15; 
  Serial.print("Temperature = ");
  Serial.print(dTemperature);
  Serial.println(" degree C");

  if (dTemperature < setpoint) {
    Serial.println("Turned On");
    publish_controls_json("", "on");
  }
  if (dTemperature > setpoint+3) {
    Serial.println("Turned Off");
    publish_controls_json("", "off");
  }
  
  delay(1000);
}
}
