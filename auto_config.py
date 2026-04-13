# Log file path: /home/pi/node_red_errors.log

"""
Header Comments for the Python Script: Node-RED Flows Updater via MQTT

Purpose:
This script runs continuously on a Raspberry Pi to dynamically update Node-RED's flows.json file based on incoming MQTT messages
on the '/system/reporting' topic. It detects new devices (e.g., with lights, switches, or sensors) from the messages, adds
corresponding Node-RED nodes (e.g., UI elements, MQTT in/out, functions) to the flows if the device is new, writes the updated
flows back to disk, and restarts Node-RED to apply changes. The script ensures no duplicates by checking for existing device
IDs in the flows.

Key Functionality:
1. Loads the initial flows.json into memory.
2. Subscribes to the MQTT topic '/system/reporting' using paho-mqtt.
3. On receiving a message:
   - Parses the JSON payload.
   - Ignores invalid JSON or messages from 'node-red'.
   - Checks if the device_id already exists in flows (by ui_group name or topics).
   - If new, adds nodes for lights, switches, and sensors.
4. For lights:
   - Handles 'dual_temp' for dual-temperature pairs (pairs from highest indices, controlling lower index gets UI for toggle,
brightness, temperature; higher skipped).
   - Adds ui_button (toggle), ui_slider (brightness, and temperature if dual), function nodes, and mqtt out in Virtual Links
tab.
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

Assumptions and Dependencies:
- Runs on Raspberry Pi with Node-RED installed and flows.json at '/home/pi/.node-red/flows.json'.
- MQTT broker at '127.0.0.1:1883' (localhost).
- Requires libraries: json, uuid, logging, subprocess, time, paho.mqtt.client (install via pip if needed).
- Virtual Links tab ID: '0c14ff671dbe21a9', Physical Links: 'c384410fdb810ed6', UI tab: 'tab_lights'.
- Broker ID reused from existing mqtt-broker node.
- Dual_temp 0 or [] ignored; >0 creates pairs (e.g., for count=12, dual_temp=2: pairs L9-L10, L11-L12; UI only for L9, L11).
- Temperature sliders: 0-255, step 5, shared mqtt out with 'set_temperature {value}'.
- No internet access; pure local operation.
- Script runs indefinitely; handle interruptions gracefully.

Potential Improvements:
- Add more error handling for MQTT disconnects.
- Support other display_types if sensors evolve beyond gauges.
- Configurable paths/IDs via env vars.

Usage:
Run with 'python3 this_script.py'. Ensure permissions for flows.json and node-red-restart.
Set ENABLE_LOGGING to True/False to enable/disable error logging.
"""

import json
import uuid
import logging
import subprocess
import time
import paho.mqtt.client as mqtt
from pathlib import Path
import sys

# Logging toggle
ENABLE_LOGGING = True # Set to False to disable logging, True to enable

# Setup logging
if ENABLE_LOGGING:
    logging.basicConfig(filename='/home/pi/node_red_errors.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
else:
    logging.basicConfig(level=logging.CRITICAL + 1)  # Disable logging by setting level above all messages

if ENABLE_LOGGING:
    logging.error("=== auto_config.py STARTED ===")
    logging.error(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.error(f"Python version: {sys.version}")
    logging.error("Trying to connect to MQTT broker...")

# Paths and constants
FLOWS_FILE = Path('/home/pi/.node-red/flows.json')
VIRTUAL_TAB_ID = "0c14ff671dbe21a9"  # Virtual Links tab ID from initial flows
PHYSICAL_TAB_ID = "c384410fdb810ed6"  # Physical Links tab ID from initial flows
UI_TAB_ID = "tab_lights"  # Reusable UI tab ID for dashboard
Y_INCREMENT = 40  # Increment for y positions

# Load initial flows
def load_flows():
    try:
        with open(FLOWS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        if ENABLE_LOGGING:
            logging.error(f"Failed to load flows.json: {e}")
        return []

# Write flows and restart Node-RED
def write_and_restart(flows):
    try:
        with open(FLOWS_FILE, 'w') as f:
            json.dump(flows, f, indent=4)
        subprocess.run(["node-red-restart"], check=True)
    except Exception as e:
        if ENABLE_LOGGING:
            logging.error(f"Failed to write flows.json or restart Node-RED: {e}")

# Find existing node by type and optional fields
def find_existing_node(flows, node_type, extra_conditions=None):
    for node in flows:
        if node.get('type') == node_type:
            if extra_conditions:
                if all(node.get(k) == v for k, v in extra_conditions.items()):
                    return node
            else:
                return node
    return None

# Get max y in a tab, optionally filtered by node_type
def get_max_y_in_tab(flows, tab_id, node_type=None):
    max_y = 0
    for node in flows:
        if node.get('z') == tab_id and 'y' in node:
            if node_type is None or node.get('type') == node_type:
                max_y = max(max_y, node['y'])
    return max_y

# Generate new node ID
def new_id():
    return str(uuid.uuid4()).replace('-', '')[:16]

# Add new node to flows
def add_node(flows, node):
    flows.append(node)
    return node['id']

# Process new message
def process_message(flows, msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        if ENABLE_LOGGING:
            logging.error("Invalid JSON in MQTT message")
        return False

    device_id = data.get('device_id')
    if device_id == "node-red":
        return False  # Ignore node-red reports

    # Check if device already exists (by ui_group name or node topics containing device_id)
    for node in flows:
        if node.get('type') == "ui_group" and node.get('name') == device_id:
            return False
        if 'topic' in node and device_id in node['topic']:
            return False
    return data  # Return data if new

# Get or create ui_tab
def get_or_create_ui_tab(flows):
    ui_tab = find_existing_node(flows, "ui_tab", {"id": UI_TAB_ID})
    if not ui_tab:
        ui_tab_id = UI_TAB_ID
        add_node(flows, {
            "id": ui_tab_id,
            "type": "ui_tab",
            "name": "Virtual Links",
            "icon": "dashboard",
            "order": 1,
            "disabled": False,
            "hidden": False
        })
    return UI_TAB_ID

# Get or create ui_group for device
def get_or_create_ui_group(flows, device_id, ui_tab_id):
    ui_group = find_existing_node(flows, "ui_group", {"name": device_id, "tab": ui_tab_id})
    if not ui_group:
        group_id = new_id()
        add_node(flows, {
            "id": group_id,
            "type": "ui_group",
            "name": device_id,
            "tab": ui_tab_id,
            "order": len([n for n in flows if n.get('type') == "ui_group"]) + 1,
            "disp": True,
            "width": "12",
            "collapse": False,
            "className": ""
        })
    else:
        group_id = ui_group['id']
    return group_id

# Get or create ui_base
def get_or_create_ui_base(flows):
    ui_base = find_existing_node(flows, "ui_base")
    if not ui_base:
        base_id = new_id()
        add_node(flows, {
            "id": base_id,
            "type": "ui_base",
            "theme": {
                "name": "theme-light",
                "lightTheme": {
                    "default": "#0094CE",
                    "baseColor": "#0094CE",
                    "baseFont": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen-Sans,Ubuntu,Cantarell,Helvetica Neue,sans-serif",
                    "edited": True,
                    "reset": False
                },
                "darkTheme": {
                    "default": "#097479",
                    "baseColor": "#097479",
                    "baseFont": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen-Sans,Ubuntu,Cantarell,Helvetica Neue,sans-serif",
                    "edited": False
                },
                "customTheme": {
                    "name": "Untitled Theme 1",
                    "default": "#4B7930",
                    "baseColor": "#4B7930",
                    "baseFont": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen-Sans,Ubuntu,Cantarell,Helvetica Neue,sans-serif"
                },
                "themeState": {
                    "base-color": {
                        "default": "#0094CE",
                        "value": "#0094CE",
                        "edited": False
                    },
                    "page-titlebar-backgroundColor": {
                        "value": "#0094CE",
                        "edited": False
                    },
                    "page-backgroundColor": {
                        "value": "#fafafa",
                        "edited": False
                    },
                    "page-sidebar-backgroundColor": {
                        "value": "#ffffff",
                        "edited": False
                    },
                    "group-textColor": {
                        "value": "#1bbfff",
                        "edited": False
                    },
                    "group-borderColor": {
                        "value": "#ffffff",
                        "edited": False
                    },
                    "group-backgroundColor": {
                        "value": "#ffffff",
                        "edited": False
                    },
                    "widget-textColor": {
                        "value": "#111111",
                        "edited": False
                    },
                    "widget-backgroundColor": {
                        "value": "#0094ce",
                        "edited": False
                    },
                    "widget-borderColor": {
                        "value": "#ffffff",
                        "edited": False
                    },
                    "base-font": {
                        "value": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen-Sans,Ubuntu,Cantarell,Helvetica Neue,sans-serif"
                    }
                },
                "angularTheme": {
                    "primary": "indigo",
                    "accents": "blue",
                    "warn": "red",
                    "background": "grey",
                    "palette": "light"
                }
            },
            "site": {
                "name": "Node-RED Dashboard",
                "hideToolbar": "false",
                "allowSwipe": "false",
                "lockMenu": "false",
                "allowTempTheme": "true",
                "dateFormat": "DD/MM/YYYY",
                "sizes": {
                    "sx": 48,
                    "sy": 48,
                    "gx": 6,
                    "gy": 6,
                    "cx": 6,
                    "cy": 6,
                    "px": 0,
                    "py": 0
                }
            }
        })
    else:
        base_id = ui_base['id']
    return base_id

# Get broker ID
def get_broker_id(flows):
    broker = find_existing_node(flows, "mqtt-broker")
    if broker:
        return broker['id']
    if ENABLE_LOGGING:
        logging.error("No mqtt-broker found in flows.json")
    return None

# Add lights nodes (maintain Virtual UI, add abbreviated state management in Physical: Interpret, Loop, Increment, OUT)
def add_lights_nodes(flows, device_id, lights, broker_id, group_id):
    count = lights.get('count', 0)
    dual_temp = lights.get('dual_temp', 0)
    if isinstance(dual_temp, list):
        dual_temp = len(dual_temp) if dual_temp else 0

    # Calculate controlling indices and skipped
    controlling_indices = []
    skipped_indices = []
    for i in range(dual_temp):
        high = count - i * 2
        low = high - 1
        controlling_indices.append(low)
        skipped_indices.append(high)
    controlling_indices.sort()

    # Get max y in virtual tab
    max_y_virtual = get_max_y_in_tab(flows, VIRTUAL_TAB_ID)
    y_start = max(max_y_virtual + Y_INCREMENT, 140)

    # Get max order in group
    max_order = 0
    for node in flows:
        if 'group' in node and node['group'] == group_id and 'order' in node:
            max_order = max(max_order, node['order'])
    order_start = max_order + 1

    # Add UI nodes in Virtual Links, grouped by light
    for index in range(1, count + 1):
        if index in skipped_indices:
            continue  # Skip higher in pairs

        l_str = f"L{index}"
        v_str = f"V{index}"
        order = order_start

        # Generate IDs
        mqtt_out_id = new_id()
        function_bright_id = new_id()
        function_temp_id = None if index not in controlling_indices else new_id()

        # MQTT out in Virtual Links
        add_node(flows, {
            "id": mqtt_out_id,
            "type": "mqtt out",
            "z": VIRTUAL_TAB_ID,
            "name": f"{device_id}/{l_str}",
            "topic": f"/lights/{device_id}/{l_str}/command",
            "qos": "2",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 510,
            "y": y_start,
            "wires": []
        })

        # Brightness function
        add_node(flows, {
            "id": function_bright_id,
            "type": "function",
            "z": VIRTUAL_TAB_ID,
            "name": "set_brightness",
            "func": "msg.payload = \"set_brightness \" + msg.payload;\nreturn msg;",
            "outputs": 1,
            "timeout": "",
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 300,
            "y": y_start + Y_INCREMENT,
            "wires": [[mqtt_out_id]]
        })

        if index in controlling_indices:
            # Temperature function
            add_node(flows, {
                "id": function_temp_id,
                "type": "function",
                "z": VIRTUAL_TAB_ID,
                "name": "set_temperature",
                "func": "msg.payload = \"set_temperature \" + msg.payload;\nreturn msg;",
                "outputs": 1,
                "timeout": "",
                "noerr": 0,
                "initialize": "",
                "finalize": "",
                "libs": [],
                "x": 300,
                "y": y_start + 2 * Y_INCREMENT,
                "wires": [[mqtt_out_id]]
            })

        # Toggle button
        add_node(flows, {
            "id": new_id(),
            "type": "ui_button",
            "z": VIRTUAL_TAB_ID,
            "name": v_str,
            "group": group_id,
            "order": order,
            "width": 3,
            "height": 1,
            "passthru": False,
            "label": f"{l_str} Toggle",
            "tooltip": "",
            "color": "",
            "bgcolor": "",
            "className": "",
            "icon": "",
            "payload": "click",
            "payloadType": "str",
            "topic": "",
            "topicType": "str",
            "x": 110,
            "y": y_start,
            "wires": [[mqtt_out_id]]
        })
        order += 1

        # Brightness slider
        add_node(flows, {
            "id": new_id(),
            "type": "ui_slider",
            "z": VIRTUAL_TAB_ID,
            "name": f"{v_str} Brightness",
            "label": f"{l_str} Brightness",
            "tooltip": "",
            "group": group_id,
            "order": order,
            "width": 3,
            "height": "",
            "passthru": True,
            "outs": "all",
            "topic": "",
            "topicType": "str",
            "min": 5,
            "max": 100,
            "step": 1,
            "className": "",
            "x": 100,
            "y": y_start + Y_INCREMENT,
            "wires": [[function_bright_id]]
        })
        order += 1

        if index in controlling_indices:
            # Temperature slider
            add_node(flows, {
                "id": new_id(),
                "type": "ui_slider",
                "z": VIRTUAL_TAB_ID,
                "name": f"{v_str} Temperature",
                "label": f"{l_str} Temperature",
                "tooltip": "",
                "group": group_id,
                "order": order,
                "width": 3,
                "height": "",
                "passthru": True,
                "outs": "all",
                "topic": "",
                "topicType": "str",
                "min": 0,
                "max": 255,
                "step": 5,
                "className": "",
                "x": 100,
                "y": y_start + 2 * Y_INCREMENT,
                "wires": [[function_temp_id]]
            })
            order += 1

        y_start += Y_INCREMENT * (3 if index in controlling_indices else 2)
        order_start = order




    # Add full state management in Physical Links for non-skipped lights (Interpret, Loop, Increment, OUT)
    max_y_physical_out = get_max_y_in_tab(flows, PHYSICAL_TAB_ID, "mqtt out")
    y_start_physical = max(max_y_physical_out + Y_INCREMENT, 40) + 20  # Shift entire block down by 20
    logging.info(f"Adding physical control nodes for {device_id} on Physical Links")

    for index in range(1, count + 1):
        if index in skipped_indices:
            continue
        l_str = f"L{index}"
        light_id = index  # For use in func strings

        # Generate IDs
        mqtt_out_id = new_id()
        interpret_id = new_id()
        inject_id = new_id()
        increment_id = new_id()

        interpret_y = y_start_physical  # Same y as MQTT OUT
        loop_y = y_start_physical + 40  # Offset to 40 for spacing

        # MQTT out in Physical Links (x=710)
        add_node(flows, {
            "id": mqtt_out_id,
            "type": "mqtt out",
            "z": PHYSICAL_TAB_ID,
            "name": f"{device_id}/{l_str}",
            "topic": f"/lights/{device_id}/{l_str}/command",
            "qos": "2",
            "retain": "true",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 710,
            "y": y_start_physical,
            "wires": []
        })

        # Interpret function (x=480, same y as MQTT OUT)
        interpret_func = f"""// Any switch → {l_str} (dual-temp)
let parts = msg.topic.split('/');
let deviceId = '{device_id}';
let lightId = {light_id};
let stateKey = `light_${{deviceId}}_L${{lightId}}_state`;
let state = flow.get(stateKey) || {{on_off:"off",brightness:100,temperature:0}};
let command = msg.payload;
let activeKey = `${{deviceId}}_L${{lightId}}`;
let active = flow.get("active_continuuous") || {{}};

// ONLY when ON
if (command==="on") {{ state.on_off="on"; delete active[activeKey]; }}
else if (command==="off") {{ state.on_off="off"; delete active[activeKey]; }}
else if (command==="click") {{ state.on_off = state.on_off==="on" ? "off" : "on"; if(state.on_off==="off") delete active[activeKey]; }}
else if (state.on_off==="on") {{
  if (command.startsWith("set_brightness ")) state.brightness = Math.max(5,Math.min(100,parseInt(command.split(' ')[1])));
  else if (command.startsWith("set_temperature ")) state.temperature = Math.max(0,Math.min(255,parseInt(command.split(' ')[1])));
  else if (command.startsWith("start_")) {{
    let a = command.split('_')[1];
    if (["brighten","dim","cool","heat"].includes(a)) {{ active[activeKey]={{action:a,startTime:Date.now()}}; flow.set("active_continuuous",active); return null; }}
  }}
  else if (command==="stop") {{ delete active[activeKey]; }}
  else return null;
}} else return null;

flow.set(stateKey,state);
msg.payload=JSON.stringify(state);
msg.topic=`/lights/${{deviceId}}/L${{lightId}}/command`;
msg.retain=true;
return msg;"""
        add_node(flows, {
            "id": interpret_id,
            "type": "function",
            "z": PHYSICAL_TAB_ID,
            "name": f"Interpret Any Switch → {l_str}",
            "func": interpret_func,
            "outputs": 1,
            "noerr": 0,
            "initialize": f"// ==== ON START: restore last state ====\nlet deviceId='{device_id}', lightId={light_id};\nlet key=`light_${{deviceId}}_L${{lightId}}_state`;\nlet saved=flow.get(key);\nif(saved) {{\n  flow.set(key,saved);\n  node.status({{fill:\"green\",shape:\"dot\",text:\"Restored\"}});\n}} else {{\n  flow.set(key,{{on_off:\"off\",brightness:100,temperature:0}});\n  node.status({{fill:\"yellow\",shape:\"dot\",text:\"Defaults\"}});\n}}\nflow.set(\"active_continuuous\",{{}});\n",
            "finalize": "",
            "libs": [],
            "x": 480,
            "y": interpret_y,
            "wires": [[f"{mqtt_out_id}"]]  # Wires to MQTT OUT
        })

        # Inject for loop (x=480, aligned with Interpret; y +40)
        add_node(flows, {
            "id": inject_id,
            "type": "inject",
            "z": PHYSICAL_TAB_ID,
            "name": "50 ms Loop",
            "repeat": "0.05",
            "once": True,
            "onceDelay": 0.1,
            "x": 480,
            "y": loop_y,
            "wires": [[f"{increment_id}"]]  # Wires to Increment (immediate right)
        })

        # Increment function (x=660; y +40)
        increment_func = f"""let deviceId='{device_id}', lightId={light_id};
let key=`light_${{deviceId}}_L${{lightId}}_state`;
let activeKey=`${{deviceId}}_L${{lightId}}`;
let active=flow.get("active_continuuous")||{{}};
if(!active[activeKey]) return null;
let state=flow.get(key);
if(!state || state.on_off!=="on") {{ delete active[activeKey]; flow.set("active_continuuous",active); return null; }}
let a=active[activeKey].action, updated=false;
if(a==="brighten" && state.brightness<100) {{ state.brightness=Math.min(100,state.brightness+2); updated=true; }}
else if(a==="dim" && state.brightness>5) {{ state.brightness=Math.max(5,state.brightness-2); updated=true; }}
else if(a==="cool" && state.temperature>0) {{ state.temperature=Math.max(0,state.temperature-5); updated=true; }}
else if(a==="heat" && state.temperature<255) {{ state.temperature=Math.min(255,state.temperature+5); updated=true; }}
else {{ delete active[activeKey]; }}
if(updated || !active[activeKey]) {{
  flow.set(key,state);
  flow.set("active_continuuous",active);
  msg.payload=JSON.stringify(state);
  msg.topic=`/lights/${{deviceId}}/L${{lightId}}/command`;
  msg.retain=true;
  return msg;
}}
return null;"""
        add_node(flows, {
            "id": increment_id,
            "type": "function",
            "z": PHYSICAL_TAB_ID,
            "name": f"Increment {l_str}",
            "func": increment_func,
            "outputs": 1,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 660,
            "y": loop_y,
            "wires": [[f"{mqtt_out_id}"]]  # Wires to MQTT OUT
        })

        y_start_physical += 80  # Adjusted for block: 40 height + 40 gap     
        


        
# Add switches nodes (mqtt in in Physical Links, unwired)
def add_switches_nodes(flows, device_id, switch_count, broker_id):
    max_y_physical_in = get_max_y_in_tab(flows, PHYSICAL_TAB_ID, "mqtt in")
    y_start = max(max_y_physical_in + Y_INCREMENT, 40)

    for index in range(1, switch_count + 1):
        s_str = f"S{index}"
        mqtt_in_id = new_id()
        logging.info(f"Adding switch {s_str} → PHYSICAL Links tab")
        add_node(flows, {
            "id": mqtt_in_id,
            "type": "mqtt in",
            "z": PHYSICAL_TAB_ID,
            "name": f"{device_id}/{s_str}",
            "topic": f"/switches/{device_id}/{s_str}/action",
            "qos": "2",
            "datatype": "auto-detect",
            "broker": broker_id,
            "nl": False,
            "rap": True,
            "rh": 0,
            "inputs": 0,
            "x": 90,
            "y": y_start,
            "wires": [[]]
        })
        y_start += Y_INCREMENT

# Add sensors nodes
def add_sensors_nodes(flows, device_id, sensors, broker_id, group_id):
    max_y_virtual = get_max_y_in_tab(flows, VIRTUAL_TAB_ID)
    y_start = max(max_y_virtual + Y_INCREMENT, 140)

    # Get max order
    max_order = 0
    for node in flows:
        if 'group' in node and node['group'] == group_id and 'order' in node:
            max_order = max(max_order, node['order'])

    order_start = max_order + 1

    for sensor in sensors:
        sensor_type = sensor['type']
        fields = sensor['fields']
        for field in fields:
            field_name = field['name']
            unit = field['unit']
            display_type = field['display_type']
            range_min = field['range']['min']
            range_max = field['range']['max']

            topic = f"/sensors/{device_id}/{sensor_type}/data" if len(fields) == 1 else f"/sensors/{device_id}/{sensor_type}/data/{field_name}"

            # Generate gauge_id first
            gauge_id = new_id()
            add_node(flows, {
                "id": gauge_id,
                "type": "ui_gauge",
                "z": VIRTUAL_TAB_ID,
                "name": f"{device_id}/{sensor_type}/{field_name}",
                "group": group_id,
                "order": order_start,
                "width": 0,
                "height": 0,
                "gtype": "gage",
                "title": field_name,
                "label": unit,
                "format": "{{value}}",
                "min": str(range_min),
                "max": str(range_max),
                "colors": ["#00b500", "#e6e600", "#ca3838"],
                "seg1": "",
                "seg2": "",
                "diff": False,
                "className": "",
                "x": 400,
                "y": y_start,
                "wires": []
            })

            # MQTT in wired to gauge
            mqtt_in_id = new_id()
            add_node(flows, {
                "id": mqtt_in_id,
                "type": "mqtt in",
                "z": VIRTUAL_TAB_ID,
                "name": f"{device_id}/{sensor_type}/{field_name}",
                "topic": topic,
                "qos": "2",
                "datatype": "auto-detect",
                "broker": broker_id,
                "nl": False,
                "rap": True,
                "rh": 0,
                "inputs": 0,
                "x": 120,
                "y": y_start,
                "wires": [[gauge_id]]
            })

            order_start += 1
            y_start += Y_INCREMENT

# MQTT callback
def on_message(client, userdata, message):
    flows = load_flows()
    data = process_message(flows, message.payload.decode())
    if not data:
        return

    broker_id = get_broker_id(flows)
    if not broker_id:
        return

    get_or_create_ui_base(flows)
    ui_tab_id = get_or_create_ui_tab(flows)
    group_id = get_or_create_ui_group(flows, data['device_id'], ui_tab_id)

    if 'lights' in data and data['lights']:
        add_lights_nodes(flows, data['device_id'], data['lights'], broker_id, group_id)

    if 'switches' in data and data['switches']:
        add_switches_nodes(flows, data['device_id'], data['switches'], broker_id)

    if 'sensors' in data and data['sensors']:
        add_sensors_nodes(flows, data['device_id'], data['sensors'], broker_id, group_id)

    write_and_restart(flows)

# MQTT setup
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
client.on_message = on_message
client.connect("127.0.0.1", 1883, 60)
client.subscribe("/system/reporting")

# Run continuously
client.loop_forever()

