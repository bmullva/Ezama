# Log file path: /home/pi/node_red_errors.log

import json
import uuid
import logging
import subprocess
import time
import paho.mqtt.client as mqtt
from pathlib import Path
import sys

ENABLE_LOGGING = True

if ENABLE_LOGGING:
    logging.basicConfig(filename='/home/pi/node_red_errors.log', level=logging.ERROR,
                        format='%(asctime)s - %(levelname)s - %(message)s')
else:
    logging.basicConfig(level=logging.CRITICAL + 1)



FLOWS_FILE = Path('/home/pi/.node-red/flows.json')
RPi1_VIRTUAL_TAB_ID = "0c14ff671dbe21a9"
RPi1_PHYSICAL_TAB_ID = "c384410fdb810ed6"
UI_TAB_ID = "tab_lights"
Y_INCREMENT = 40
VIRTUAL_PAIR_HEIGHT = 200
PHYSICAL_PAIR_HEIGHT = 160


def load_flows():
    try:
        with open(FLOWS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        if ENABLE_LOGGING:
            logging.error(f"Failed to load flows.json: {e}")
        return []


def write_and_restart(flows):
    try:
        with open(FLOWS_FILE, 'w') as f:
            json.dump(flows, f, indent=4)
        subprocess.run(["node-red-restart"], check=True)
    except Exception as e:
        if ENABLE_LOGGING:
            logging.error(f"Failed to write flows.json or restart Node-RED: {e}")


def find_existing_node(flows, node_type, extra_conditions=None):
    for node in flows:
        if node.get('type') == node_type:
            if extra_conditions:
                if all(node.get(k) == v for k, v in extra_conditions.items()):
                    return node
            else:
                return node
    return None


def get_max_y_in_tab(flows, tab_id, node_type=None):
    max_y = 0
    for node in flows:
        if node.get('z') == tab_id and 'y' in node:
            if node_type is None or node.get('type') == node_type:
                max_y = max(max_y, node['y'])
    return max_y


def new_id():
    return str(uuid.uuid4()).replace('-', '')[:16]


def add_node(flows, node):
    flows.append(node)
    return node['id']


def get_or_create_tab(flows, tab_name):
    for node in flows:
        if node.get('type') == 'tab' and node.get('label') == tab_name:
            return node['id']
    tab_id = new_id()
    add_node(flows, {
        "id": tab_id,
        "type": "tab",
        "label": tab_name,
        "disabled": False,
        "info": "",
        "env": []
    })
    return tab_id


def get_or_create_device_tabs(flows, device_id):
    if device_id == "RPi1":
        rpi1_virt = any(n.get('type') == 'tab' and n.get('id') == RPi1_VIRTUAL_TAB_ID for n in flows)
        rpi1_phys = any(n.get('type') == 'tab' and n.get('id') == RPi1_PHYSICAL_TAB_ID for n in flows)
        if not rpi1_virt:
            add_node(flows, {
                "id": RPi1_VIRTUAL_TAB_ID,
                "type": "tab",
                "label": "Virtual Links",
                "disabled": False,
                "info": "",
                "env": []
            })
        if not rpi1_phys:
            add_node(flows, {
                "id": RPi1_PHYSICAL_TAB_ID,
                "type": "tab",
                "label": "Physical Links",
                "disabled": False,
                "info": "",
                "env": []
            })
        return (RPi1_VIRTUAL_TAB_ID, RPi1_PHYSICAL_TAB_ID)
    else:
        virtual_tab_id = get_or_create_tab(flows, f"{device_id} Virtual")
        physical_tab_id = get_or_create_tab(flows, f"{device_id} Physical")
        return (virtual_tab_id, physical_tab_id)


def get_or_create_sensors_tab(flows):
    return get_or_create_tab(flows, "Sensors")


def process_message(flows, msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        if ENABLE_LOGGING:
            logging.error("Invalid JSON in MQTT message")
        return False

    device_id = data.get('device_id')
    if device_id == "node-red":
        return False

    for node in flows:
        if node.get('type') == "ui_group" and node.get('name') == device_id:
            return False
        if 'topic' in node and device_id in node['topic']:
            return False
    return data


def get_or_create_ui_tab(flows):
    ui_tab = find_existing_node(flows, "ui_tab", {"id": UI_TAB_ID})
    if not ui_tab:
        add_node(flows, {
            "id": UI_TAB_ID,
            "type": "ui_tab",
            "name": "Virtual Links",
            "icon": "dashboard",
            "order": 1,
            "disabled": False,
            "hidden": False
        })
    return UI_TAB_ID


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
                    "base-color": {"default": "#0094CE", "value": "#0094CE", "edited": False},
                    "page-titlebar-backgroundColor": {"value": "#0094CE", "edited": False},
                    "page-backgroundColor": {"value": "#fafafa", "edited": False},
                    "page-sidebar-backgroundColor": {"value": "#ffffff", "edited": False},
                    "group-textColor": {"value": "#1bbfff", "edited": False},
                    "group-borderColor": {"value": "#ffffff", "edited": False},
                    "group-backgroundColor": {"value": "#ffffff", "edited": False},
                    "widget-textColor": {"value": "#111111", "edited": False},
                    "widget-backgroundColor": {"value": "#0094ce", "edited": False},
                    "widget-borderColor": {"value": "#ffffff", "edited": False},
                    "base-font": {"value": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Oxygen-Sans,Ubuntu,Cantarell,Helvetica Neue,sans-serif"}
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
                "sizes": {"sx": 48, "sy": 48, "gx": 6, "gy": 6, "cx": 6, "cy": 6, "px": 0, "py": 0}
            }
        })
    else:
        base_id = ui_base['id']
    return base_id


def get_broker_id(flows):
    broker = find_existing_node(flows, "mqtt-broker")
    if broker:
        return broker['id']
    if ENABLE_LOGGING:
        logging.error("No mqtt-broker found in flows.json")
    return None


def _add_physical_light(flows, device_id, light_idx, broker_id, physical_tab_id, y_base):
    l_str = f"L{light_idx}"
    mqtt_out_id = new_id()
    interpret_id = new_id()
    inject_id = new_id()
    increment_id = new_id()

    add_node(flows, {
        "id": mqtt_out_id,
        "type": "mqtt out",
        "z": physical_tab_id,
        "name": f"{device_id}/{l_str}",
        "topic": f"/lights/{device_id}/{l_str}/command",
        "qos": "2",
        "retain": "true",
        "respTopic": "", "contentType": "", "userProps": "", "correl": "", "expiry": "",
        "broker": broker_id,
        "x": 710, "y": y_base,
        "wires": []
    })

    interpret_func = f"""// Any switch -> {l_str}
let deviceId = '{device_id}';
let lightId = {light_idx};
let stateKey = `light_${{deviceId}}_L${{lightId}}_state`;
let state = flow.get(stateKey) || {{on_off:"off",brightness:100,temperature:0}};
let command = msg.payload;
let activeKey = `${{deviceId}}_L${{lightId}}`;
let active = flow.get("active_continuuous") || {{}};

if (command === "on") {{ state.on_off = "on"; delete active[activeKey]; }}
else if (command === "off") {{ state.on_off = "off"; delete active[activeKey]; }}
else if (command === "click") {{ state.on_off = state.on_off === "on" ? "off" : "on"; if (state.on_off === "off") delete active[activeKey]; }}
else if (state.on_off === "on") {{
    if (command.startsWith("set_brightness ")) state.brightness = Math.max(5, Math.min(100, parseInt(command.split(" ")[1])));
    else if (command.startsWith("set_temperature ")) state.temperature = Math.max(0, Math.min(255, parseInt(command.split(" ")[1])));
    else if (command.startsWith("start_")) {{
        let a = command.split("_")[1];
        if (["brighten","dim","cool","heat"].includes(a)) {{ active[activeKey] = {{action:a, startTime:Date.now()}}; flow.set("active_continuuous", active); return null; }}
    }}
    else if (command === "stop") {{ delete active[activeKey]; }}
    else return null;
}} else return null;

flow.set(stateKey, state);
msg.payload = JSON.stringify(state);
msg.topic = `/lights/${{deviceId}}/L${{lightId}}/command`;
msg.retain = true;
return msg;"""

    init_func = f"""let deviceId = '{device_id}', lightId = {light_idx};
let key = `light_${{deviceId}}_L${{lightId}}_state`;
let saved = flow.get(key);
if (saved) {{
    flow.set(key, saved);
    node.status({{fill:"green", shape:"dot", text:"Restored"}});
}} else {{
    flow.set(key, {{on_off:"off", brightness:100, temperature:0}});
    node.status({{fill:"yellow", shape:"dot", text:"Defaults"}});
}}
flow.set("active_continuuous", {{}});"""

    add_node(flows, {
        "id": interpret_id,
        "type": "function",
        "z": physical_tab_id,
        "name": f"Interpret Any Switch -> {l_str}",
        "func": interpret_func,
        "outputs": 1,
        "noerr": 0,
        "initialize": init_func,
        "finalize": "",
        "libs": [],
        "x": 480, "y": y_base,
        "wires": [[mqtt_out_id]]
    })

    add_node(flows, {
        "id": inject_id,
        "type": "inject",
        "z": physical_tab_id,
        "name": "50 ms Loop",
        "repeat": "0.05",
        "once": True,
        "onceDelay": 0.1,
        "x": 480, "y": y_base + 40,
        "wires": [[increment_id]]
    })

    increment_func = f"""let deviceId = '{device_id}', lightId = {light_idx};
let key = `light_${{deviceId}}_L${{lightId}}_state`;
let activeKey = `${{deviceId}}_L${{lightId}}`;
let active = flow.get("active_continuuous") || {{}};
if (!active[activeKey]) return null;
let state = flow.get(key);
if (!state || state.on_off !== "on") {{ delete active[activeKey]; flow.set("active_continuuous", active); return null; }}
let a = active[activeKey].action, updated = false;
if (a === "brighten" && state.brightness < 100) {{ state.brightness = Math.min(100, state.brightness + 2); updated = true; }}
else if (a === "dim" && state.brightness > 5) {{ state.brightness = Math.max(5, state.brightness - 2); updated = true; }}
else if (a === "cool" && state.temperature > 0) {{ state.temperature = Math.max(0, state.temperature - 5); updated = true; }}
else if (a === "heat" && state.temperature < 255) {{ state.temperature = Math.min(255, state.temperature + 5); updated = true; }}
else {{ delete active[activeKey]; }}
if (updated || !active[activeKey]) {{
    flow.set(key, state);
    flow.set("active_continuuous", active);
    msg.payload = JSON.stringify(state);
    msg.topic = `/lights/${{deviceId}}/L${{lightId}}/command`;
    msg.retain = true;
    return msg;
}}
return null;"""

    add_node(flows, {
        "id": increment_id,
        "type": "function",
        "z": physical_tab_id,
        "name": f"Increment {l_str}",
        "func": increment_func,
        "outputs": 1,
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 660, "y": y_base + 40,
        "wires": [[mqtt_out_id]]
    })


def add_lights_nodes(flows, device_id, lights, broker_id, group_id, virtual_tab_id, physical_tab_id):
    count = lights.get('count', 0)
    dual_temp = lights.get('dual_temp', 0)
    if isinstance(dual_temp, list):
        dual_temp = len(dual_temp) if dual_temp else 0

    skipped_indices = set()
    for i in range(dual_temp):
        high = count - i * 2
        skipped_indices.add(high)

    max_y_virtual = get_max_y_in_tab(flows, virtual_tab_id)
    y_base_virtual = max(max_y_virtual + Y_INCREMENT, 140)

    max_y_physical = get_max_y_in_tab(flows, physical_tab_id)
    y_base_physical = max(max_y_physical + Y_INCREMENT, 40)

    max_order = max((n.get('order', 0) for n in flows if n.get('group') == group_id), default=0)
    order_start = max_order + 1

    num_pairs = (count + 1) // 2
    for pair_idx in range(num_pairs):
        odd = pair_idx * 2 + 1
        even = pair_idx * 2 + 2
        is_dual_pair = (even in skipped_indices)

        v_base = y_base_virtual + pair_idx * VIRTUAL_PAIR_HEIGHT
        p_base = y_base_physical + pair_idx * PHYSICAL_PAIR_HEIGHT

        odd_str = f"L{odd}"
        odd_v_str = f"V{odd}"
        mqtt_out_odd_id = new_id()
        func_bright_odd_id = new_id()
        func_temp_odd_id = new_id() if is_dual_pair else None

        # Virtual: odd MQTT out
        add_node(flows, {
            "id": mqtt_out_odd_id,
            "type": "mqtt out",
            "z": virtual_tab_id,
            "name": f"{device_id}/{odd_str}",
            "topic": f"/lights/{device_id}/{odd_str}/command",
            "qos": "2",
            "retain": "false",
            "respTopic": "", "contentType": "", "userProps": "", "correl": "", "expiry": "",
            "broker": broker_id,
            "x": 510, "y": v_base,
            "wires": []
        })

        # Virtual: odd toggle (y = v_base + 0)
        add_node(flows, {
            "id": new_id(),
            "type": "ui_button",
            "z": virtual_tab_id,
            "name": odd_v_str,
            "group": group_id,
            "order": order_start,
            "width": 3, "height": 1,
            "passthru": False,
            "label": f"{odd_str} Toggle",
            "tooltip": "", "color": "", "bgcolor": "", "className": "", "icon": "",
            "payload": "click", "payloadType": "str",
            "topic": "", "topicType": "str",
            "x": 110, "y": v_base,
            "wires": [[mqtt_out_odd_id]]
        })
        order_start += 1

        # Virtual: odd brightness slider (y = v_base + 40)
        add_node(flows, {
            "id": new_id(),
            "type": "ui_slider",
            "z": virtual_tab_id,
            "name": f"{odd_v_str} Brightness",
            "label": f"{odd_str} Brightness",
            "tooltip": "",
            "group": group_id,
            "order": order_start,
            "width": 3, "height": "",
            "passthru": True, "outs": "all",
            "topic": "", "topicType": "str",
            "min": 5, "max": 100, "step": 1,
            "className": "",
            "x": 100, "y": v_base + 40,
            "wires": [[func_bright_odd_id]]
        })
        order_start += 1

        add_node(flows, {
            "id": func_bright_odd_id,
            "type": "function",
            "z": virtual_tab_id,
            "name": "set_brightness",
            "func": "msg.payload = \"set_brightness \" + msg.payload;\nreturn msg;",
            "outputs": 1, "timeout": "", "noerr": 0, "initialize": "", "finalize": "", "libs": [],
            "x": 300, "y": v_base + 40,
            "wires": [[mqtt_out_odd_id]]
        })

        if is_dual_pair:
            # Virtual: odd temperature slider (y = v_base + 80)
            add_node(flows, {
                "id": new_id(),
                "type": "ui_slider",
                "z": virtual_tab_id,
                "name": f"{odd_v_str} Temperature",
                "label": f"{odd_str} Temperature",
                "tooltip": "",
                "group": group_id,
                "order": order_start,
                "width": 3, "height": "",
                "passthru": True, "outs": "all",
                "topic": "", "topicType": "str",
                "min": 0, "max": 255, "step": 5,
                "className": "",
                "x": 100, "y": v_base + 80,
                "wires": [[func_temp_odd_id]]
            })
            order_start += 1

            add_node(flows, {
                "id": func_temp_odd_id,
                "type": "function",
                "z": virtual_tab_id,
                "name": "set_temperature",
                "func": "msg.payload = \"set_temperature \" + msg.payload;\nreturn msg;",
                "outputs": 1, "timeout": "", "noerr": 0, "initialize": "", "finalize": "", "libs": [],
                "x": 300, "y": v_base + 80,
                "wires": [[mqtt_out_odd_id]]
            })
        else:
            # Virtual: even light nodes (y = v_base + 120 and v_base + 160)
            if even <= count:
                even_str = f"L{even}"
                even_v_str = f"V{even}"
                mqtt_out_even_id = new_id()
                func_bright_even_id = new_id()

                add_node(flows, {
                    "id": mqtt_out_even_id,
                    "type": "mqtt out",
                    "z": virtual_tab_id,
                    "name": f"{device_id}/{even_str}",
                    "topic": f"/lights/{device_id}/{even_str}/command",
                    "qos": "2",
                    "retain": "false",
                    "respTopic": "", "contentType": "", "userProps": "", "correl": "", "expiry": "",
                    "broker": broker_id,
                    "x": 510, "y": v_base + 120,
                    "wires": []
                })

                add_node(flows, {
                    "id": new_id(),
                    "type": "ui_button",
                    "z": virtual_tab_id,
                    "name": even_v_str,
                    "group": group_id,
                    "order": order_start,
                    "width": 3, "height": 1,
                    "passthru": False,
                    "label": f"{even_str} Toggle",
                    "tooltip": "", "color": "", "bgcolor": "", "className": "", "icon": "",
                    "payload": "click", "payloadType": "str",
                    "topic": "", "topicType": "str",
                    "x": 110, "y": v_base + 120,
                    "wires": [[mqtt_out_even_id]]
                })
                order_start += 1

                add_node(flows, {
                    "id": new_id(),
                    "type": "ui_slider",
                    "z": virtual_tab_id,
                    "name": f"{even_v_str} Brightness",
                    "label": f"{even_str} Brightness",
                    "tooltip": "",
                    "group": group_id,
                    "order": order_start,
                    "width": 3, "height": "",
                    "passthru": True, "outs": "all",
                    "topic": "", "topicType": "str",
                    "min": 5, "max": 100, "step": 1,
                    "className": "",
                    "x": 100, "y": v_base + 160,
                    "wires": [[func_bright_even_id]]
                })
                order_start += 1

                add_node(flows, {
                    "id": func_bright_even_id,
                    "type": "function",
                    "z": virtual_tab_id,
                    "name": "set_brightness",
                    "func": "msg.payload = \"set_brightness \" + msg.payload;\nreturn msg;",
                    "outputs": 1, "timeout": "", "noerr": 0, "initialize": "", "finalize": "", "libs": [],
                    "x": 300, "y": v_base + 160,
                    "wires": [[mqtt_out_even_id]]
                })

        # Physical: odd light always
        _add_physical_light(flows, device_id, odd, broker_id, physical_tab_id, p_base)
        # Physical: even light only if single-temp pair
        if not is_dual_pair and even <= count:
            _add_physical_light(flows, device_id, even, broker_id, physical_tab_id, p_base + 80)


def add_switches_nodes(flows, device_id, switch_count, broker_id, physical_tab_id):
    max_y = get_max_y_in_tab(flows, physical_tab_id, "mqtt in")
    y_start = max(max_y + Y_INCREMENT, 40)

    for index in range(1, switch_count + 1):
        s_str = f"S{index}"
        add_node(flows, {
            "id": new_id(),
            "type": "mqtt in",
            "z": physical_tab_id,
            "name": f"{device_id}/{s_str}",
            "topic": f"/switches/{device_id}/{s_str}/action",
            "qos": "2",
            "datatype": "auto-detect",
            "broker": broker_id,
            "nl": False, "rap": True, "rh": 0, "inputs": 0,
            "x": 90, "y": y_start,
            "wires": [[]]
        })
        y_start += Y_INCREMENT


def add_sensors_nodes(flows, device_id, sensors, broker_id, group_id, sensors_tab_id):
    max_y = get_max_y_in_tab(flows, sensors_tab_id)
    y_start = max(max_y + Y_INCREMENT, 140)

    max_order = max((n.get('order', 0) for n in flows if n.get('group') == group_id), default=0)
    order_start = max_order + 1

    for sensor in sensors:
        sensor_type = sensor['type']
        fields = sensor['fields']
        for field in fields:
            field_name = field['name']
            unit = field['unit']
            range_min = field['range']['min']
            range_max = field['range']['max']

            topic = (f"/sensors/{device_id}/{sensor_type}/data" if len(fields) == 1
                     else f"/sensors/{device_id}/{sensor_type}/data/{field_name}")

            gauge_id = new_id()
            add_node(flows, {
                "id": gauge_id,
                "type": "ui_gauge",
                "z": sensors_tab_id,
                "name": f"{device_id}/{sensor_type}/{field_name}",
                "group": group_id,
                "order": order_start,
                "width": 0, "height": 0,
                "gtype": "gage",
                "title": field_name,
                "label": unit,
                "format": "{{value}}",
                "min": str(range_min),
                "max": str(range_max),
                "colors": ["#00b500", "#e6e600", "#ca3838"],
                "seg1": "", "seg2": "",
                "diff": False, "className": "",
                "x": 400, "y": y_start,
                "wires": []
            })

            mqtt_in_id = new_id()
            add_node(flows, {
                "id": mqtt_in_id,
                "type": "mqtt in",
                "z": sensors_tab_id,
                "name": f"{device_id}/{sensor_type}/{field_name}",
                "topic": topic,
                "qos": "2",
                "datatype": "auto-detect",
                "broker": broker_id,
                "nl": False, "rap": True, "rh": 0, "inputs": 0,
                "x": 120, "y": y_start,
                "wires": [[gauge_id]]
            })

            order_start += 1
            y_start += Y_INCREMENT


def on_message(client, userdata, message):
    flows = load_flows()
    data = process_message(flows, message.payload.decode())
    if not data:
        return

    broker_id = get_broker_id(flows)
    if not broker_id:
        return

    device_id = data['device_id']
    get_or_create_ui_base(flows)
    ui_tab_id = get_or_create_ui_tab(flows)
    group_id = get_or_create_ui_group(flows, device_id, ui_tab_id)

    has_lights = 'lights' in data and data['lights']
    has_switches = 'switches' in data and data['switches']
    has_sensors = 'sensors' in data and data['sensors']

    if has_lights or has_switches:
        virtual_tab_id, physical_tab_id = get_or_create_device_tabs(flows, device_id)
        if has_lights:
            add_lights_nodes(flows, device_id, data['lights'], broker_id, group_id,
                             virtual_tab_id, physical_tab_id)
        if has_switches:
            add_switches_nodes(flows, device_id, data['switches'], broker_id, physical_tab_id)

    if has_sensors:
        sensors_tab_id = get_or_create_sensors_tab(flows)
        add_sensors_nodes(flows, data['device_id'], data['sensors'], broker_id, group_id, sensors_tab_id)

    write_and_restart(flows)


if __name__ == "__main__":
    if ENABLE_LOGGING:
        logging.error("=== auto_config.py STARTED ===")
        logging.error(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        logging.error(f"Python version: {sys.version}")
        logging.error("Trying to connect to MQTT broker...")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.on_message = on_message
    client.connect("127.0.0.1", 1883, 60)
    client.subscribe("/system/reporting")
    client.loop_forever()
