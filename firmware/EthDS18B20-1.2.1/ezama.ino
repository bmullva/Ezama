#define ETH_CLK_MODE ETH_CLOCK_GPIO0_IN
#define ETH_POWER_PIN 16
#define ETH_TYPE ETH_PHY_LAN8720
#define ETH_ADDR 1
#define ETH_MDC_PIN 23
#define ETH_MDIO_PIN 18


void WiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      Serial.println("ETH Started");
      ETH.setHostname("esp32-ethernet");
      break;

    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("ETH Connected");
      break;

    case ARDUINO_EVENT_ETH_GOT_IP:
      // Derive device_id from last 6 hex digits of MAC
      { String _mac = ETH.macAddress(); _mac.replace(":", ""); _mac.substring(_mac.length() - 6).toCharArray(device_id, sizeof(device_id)); }
      Serial.print("ETH MAC: ");
      Serial.print(ETH.macAddress());
      Serial.print(", IPv4: ");
      Serial.print(ETH.localIP());
      if (ETH.fullDuplex()) {
        Serial.print(", FULL_DUPLEX");
      }
      Serial.print(", ");
      Serial.print(ETH.linkSpeed());
      Serial.println("Mbps");

      eth_connected = true;

      // --- OTA setup happens here ---
      ArduinoOTA.setHostname(("WT32-ETH01-" + String(device_id)).c_str());
      ArduinoOTA.setPassword("otapassword");
      ArduinoOTA.setPort(3232);

      ArduinoOTA.onStart([]() { Serial.println("OTA: Start updating"); });
      ArduinoOTA.onEnd([]() { Serial.println("\nOTA: End"); });
      ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("OTA: Progress: %u%%\r", (progress / (total / 100)));
      });
      ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("OTA: Error[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
        else if (error == OTA_END_ERROR) Serial.println("End Failed");
      });

      ArduinoOTA.begin();   // start OTA server AFTER IP is assigned
      Serial.println("OTA ready on port 3232");
      
      // --- MQTT setup also here ---
      findMQTTserver();
      mqttClient.setServer(mqtt_server, mqtt_port);
      mqttClient.setCallback(mqttCallback);
      mqttClient.subscribe(mqtt_topic_subscribe);

      break;

    case ARDUINO_EVENT_ETH_DISCONNECTED:
      Serial.println("ETH Disconnected");
      eth_connected = false;
      break;

    case ARDUINO_EVENT_ETH_STOP:
      Serial.println("ETH Stopped");
      eth_connected = false;
      break;

    default:
      break;
  }
}



void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived on topic: ");
  Serial.print(topic);
  Serial.print(". Message: ");
  String messageTemp;
  for (int i = 0; i < length; i++) {
    messageTemp += (char)payload[i];
  }
  Serial.println(messageTemp);
  if (strcmp(topic, "/system/broadcast") == 0) {
    if (messageTemp == "ping") {publish_reporting_json();}
    if (messageTemp == "restart") { 
      delay(10000);  // Delay before restarting
      ESP.restart();
    }
  }
  else if (strcmp(topic, device_id) == 0) {
    if (messageTemp == "restart") {ESP.restart();}
    if (messageTemp == "reset") {
      for (int i = 0; i < 222; i++) {EEPROM.write(i, 255);}
      for (int i = 231; i < 512; i++) {EEPROM.write(i, 255);}
      EEPROM.write(230, 's');
      EEPROM.commit();
      ESP.restart();
    }
  }
  else if (strcmp(topic, "password") == 0) {
    int password_length = messageTemp.length();
    if (password_length > 0 && password_length <= 64) {  // Ensure password is within bounds
      EEPROM.write(password_length_addr, password_length);
      for (int i = 0; i < password_length; i++) {
        EEPROM.write(password_addr + i, messageTemp[i]);
      }
      EEPROM.commit();
      ESP.restart();
    }
    else {
      Serial.println("Invalid password length.");
    }
  }
  else {
    receive_controls_json(topic, messageTemp);
  }
}

void reconnect() {
  while (!mqttClient.connected()) {
    Serial.print("Attempting MQTT connection...");
    if (mqttClient.connect("ESP32Client")) {
      Serial.println("connected");
      mqttClient.subscribe(mqtt_topic_subscribe);
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void findMQTTserver() {
  mqttClient.setServer(mqtt_ip_1, 1883);
  if (mqttClient.connect(device_id)) {
    mqtt_server = mqtt_ip_1;
    return;  // Connected successfully
  }
  mqttClient.setServer(mqtt_ip_2, 1883);
  if (mqttClient.connect(device_id)) {
    mqtt_server = mqtt_ip_2;
    return;  // Connected successfully
  }
  mqttClient.setServer(mqtt_ip_3, 1883);
  if (mqttClient.connect(device_id)) {
    mqtt_server = mqtt_ip_3;
    return;  // Connected successfully
  }
}

void ezama_setup() {
  EEPROM.begin(512);


  Serial.println("Ether Switch Begin\n");

  // Register WiFi/Ethernet event handler
  WiFi.onEvent(WiFiEvent);

  // Start Ethernet
  Serial.printf("%d\n\r", ETH.begin(ETH_ADDR, ETH_POWER_PIN,
                                   ETH_MDC_PIN, ETH_MDIO_PIN,
                                   ETH_TYPE, ETH_CLK_MODE));

  // Don’t call findMQTTserver() or ArduinoOTA.begin() here anymore —
  // they are now handled in ARDUINO_EVENT_ETH_GOT_IP
}


void ezama_setup_orig() {
  EEPROM.begin(512);
  for (int i = 0; i < 8; i++) {
    device_id[i] = char(EEPROM.read(222 + i));
    }
  Serial.println("Ether Switch Begin\n");
  WiFi.onEvent(WiFiEvent);
  Serial.printf("%d\n\r", ETH.begin(ETH_ADDR, ETH_POWER_PIN, ETH_MDC_PIN, ETH_MDIO_PIN, ETH_TYPE, ETH_CLK_MODE));
  findMQTTserver();
  mqttClient.subscribe(mqtt_topic_subscribe);
  //mqttClient.setServer(mqtt_server, mqtt_port);
}

void ezama_loop() {
  if (!mqttClient.connected()) {
    reconnect();
  }
  mqttClient.loop();
}
