import subprocess
import sys
import os
import time
import json
import paho.mqtt.client as mqtt
sys.path.insert(0, '/home/pi/Ezama')
from auto_config import (
    find_existing_node, new_id, add_node,
    get_or_create_ui_tab, get_or_create_ui_group, get_broker_id,
    _add_physical_light,
    RPi1_VIRTUAL_TAB_ID, RPi1_PHYSICAL_TAB_ID
)

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
FLOWS_PATH = os.path.expanduser("~/.node-red/flows.json")
DISCOVERY_TIMEOUT = 12


def load_flows():
    with open(FLOWS_PATH, 'r') as f:
        return json.load(f)


def backup_and_save_flows(flows):
    ts = time.strftime('%Y%m%d_%H%M%S')
    backup = FLOWS_PATH + f'.bak.{ts}'
    subprocess.run(['cp', FLOWS_PATH, backup], check=True)
    print(f"flows.json backed up to {backup}")
    with open(FLOWS_PATH, 'w') as f:
        json.dump(flows, f, indent=4)


def discover_light_boards():
    devices = {}

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if "lights" in data and "device_id" in data:
                devices[data["device_id"]] = data
        except Exception:
            pass

    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.on_message = on_message
    mqttc.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqttc.subscribe("/system/reporting")
    mqttc.loop_start()

    print(f"Listening for light boards ({DISCOVERY_TIMEOUT}s)...", flush=True)
    time.sleep(DISCOVERY_TIMEOUT)

    mqttc.loop_stop()
    mqttc.disconnect()
    return devices


def get_device_tab_ids(flows, device_id):
    if device_id == "RPi1":
        return RPi1_VIRTUAL_TAB_ID, RPi1_PHYSICAL_TAB_ID
    v_id = p_id = None
    for node in flows:
        if node.get('type') == 'tab':
            label = node.get('label', '')
            if label == f"{device_id} Virtual":
                v_id = node['id']
            elif label == f"{device_id} Physical":
                p_id = node['id']
    return v_id, p_id


def read_current_dual_temp(flows, device_id):
    group_id = None
    for node in flows:
        if node.get('type') == 'ui_group' and node.get('name') == device_id:
            group_id = node['id']
            break
    if not group_id:
        return 0
    return sum(1 for n in flows
               if n.get('type') == 'ui_slider'
               and n.get('group') == group_id
               and 'Temperature' in n.get('label', ''))


def increase_dual_temp(flows, device_id, count, old_val, new_val):
    """Convert pairs from single -> dual, highest-index pairs first."""
    virtual_tab_id, physical_tab_id = get_device_tab_ids(flows, device_id)
    broker_id = get_broker_id(flows)

    for i in range(old_val, new_val):
        even = count - i * 2   # e.g. count=12, i=0 -> even=12, i=1 -> even=10
        odd = even - 1

        # --- Virtual ---
        odd_toggle = next((n for n in flows
                           if n.get('type') == 'ui_button'
                           and n.get('name') == f"V{odd}"
                           and n.get('z') == virtual_tab_id), None)
        if odd_toggle is None:
            print(f"  Warning: could not find toggle for V{odd}, skipping pair")
            continue
        v_base = odd_toggle['y']
        group_id = odd_toggle.get('group')

        odd_mqtt_out = next((n for n in flows
                             if n.get('type') == 'mqtt out'
                             and n.get('topic') == f"/lights/{device_id}/L{odd}/command"
                             and n.get('z') == virtual_tab_id), None)
        if not odd_mqtt_out:
            print(f"  Warning: could not find virtual mqtt out for L{odd}, skipping pair")
            continue

        # Add temperature slider + function at v_base + 80
        func_temp_id = new_id()
        add_node(flows, {
            "id": new_id(),
            "type": "ui_slider",
            "z": virtual_tab_id,
            "name": f"V{odd} Temperature",
            "label": f"L{odd} Temperature",
            "tooltip": "",
            "group": group_id,
            "order": odd_toggle.get('order', 0) + 2,
            "width": 3, "height": "",
            "passthru": True, "outs": "all",
            "topic": "", "topicType": "str",
            "min": 0, "max": 255, "step": 5,
            "className": "",
            "x": 100, "y": v_base + 80,
            "wires": [[func_temp_id]]
        })
        add_node(flows, {
            "id": func_temp_id,
            "type": "function",
            "z": virtual_tab_id,
            "name": "set_temperature",
            "func": "msg.payload = \"set_temperature \" + msg.payload;\nreturn msg;",
            "outputs": 1, "timeout": "", "noerr": 0, "initialize": "", "finalize": "", "libs": [],
            "x": 300, "y": v_base + 80,
            "wires": [[odd_mqtt_out['id']]]
        })

        # Remove even light's virtual nodes
        ids_to_remove = set()
        for node in flows:
            if node.get('z') != virtual_tab_id:
                continue
            name = node.get('name', '')
            topic = node.get('topic', '')
            if name == f"V{even}":
                ids_to_remove.add(node['id'])
            elif name == f"V{even} Brightness":
                ids_to_remove.add(node['id'])
            elif topic == f"/lights/{device_id}/L{even}/command":
                ids_to_remove.add(node['id'])
            elif node.get('type') == 'function' and name == 'set_brightness' and node.get('y') == v_base + 160:
                ids_to_remove.add(node['id'])
        remove_stale_wires(flows, ids_to_remove)
        flows[:] = [n for n in flows if n.get('id') not in ids_to_remove]

        # --- Physical ---
        odd_interpret = next((n for n in flows
                              if n.get('type') == 'function'
                              and n.get('z') == physical_tab_id
                              and 'Interpret' in n.get('name', '')
                              and f"L{odd}" in n.get('name', '')), None)
        if odd_interpret is None:
            print(f"  Warning: could not find Interpret node for L{odd}, skipping physical")
            continue
        p_base = odd_interpret['y']

        # Remove even light's physical nodes
        ids_to_remove = set()
        for node in flows:
            if node.get('z') != physical_tab_id:
                continue
            name = node.get('name', '')
            topic = node.get('topic', '')
            if f"L{even}" in name:  # Interpret and Increment nodes
                ids_to_remove.add(node['id'])
            elif topic == f"/lights/{device_id}/L{even}/command":  # mqtt out
                ids_to_remove.add(node['id'])
            elif node.get('type') == 'inject' and node.get('y') == p_base + 120:  # even's 50ms loop
                ids_to_remove.add(node['id'])
        remove_stale_wires(flows, ids_to_remove)
        flows[:] = [n for n in flows if n.get('id') not in ids_to_remove]

        print(f"  Pair L{odd}/L{even}: converted to dual (L{even} nodes removed, temp slider added for L{odd})")


def decrease_dual_temp(flows, device_id, count, old_val, new_val):
    """Convert pairs from dual -> single, highest-index pairs first."""
    virtual_tab_id, physical_tab_id = get_device_tab_ids(flows, device_id)
    broker_id = get_broker_id(flows)

    for i in range(new_val, old_val):
        even = count - i * 2
        odd = even - 1

        # --- Virtual ---
        odd_toggle = next((n for n in flows
                           if n.get('type') == 'ui_button'
                           and n.get('name') == f"V{odd}"
                           and n.get('z') == virtual_tab_id), None)
        if odd_toggle is None:
            print(f"  Warning: could not find toggle for V{odd}, skipping pair")
            continue
        v_base = odd_toggle['y']
        group_id = odd_toggle.get('group')

        odd_mqtt_out = next((n for n in flows
                             if n.get('type') == 'mqtt out'
                             and n.get('topic') == f"/lights/{device_id}/L{odd}/command"
                             and n.get('z') == virtual_tab_id), None)
        if not odd_mqtt_out:
            print(f"  Warning: could not find virtual mqtt out for L{odd}, skipping pair")
            continue

        # Remove temperature slider + set_temperature function for odd light
        ids_to_remove = set()
        for node in flows:
            if node.get('z') != virtual_tab_id:
                continue
            if node.get('type') == 'ui_slider' and node.get('name') == f"V{odd} Temperature":
                ids_to_remove.add(node['id'])
            elif node.get('type') == 'function' and node.get('name') == 'set_temperature' and node.get('y') == v_base + 80:
                ids_to_remove.add(node['id'])
        remove_stale_wires(flows, ids_to_remove)
        flows[:] = [n for n in flows if n.get('id') not in ids_to_remove]

        # Add even light's nodes at v_base + 120 and v_base + 160
        even_mqtt_out_id = new_id()
        even_func_id = new_id()
        add_node(flows, {
            "id": even_mqtt_out_id,
            "type": "mqtt out",
            "z": virtual_tab_id,
            "name": f"{device_id}/L{even}",
            "topic": f"/lights/{device_id}/L{even}/command",
            "qos": "2", "retain": "false",
            "respTopic": "", "contentType": "", "userProps": "", "correl": "", "expiry": "",
            "broker": broker_id,
            "x": 510, "y": v_base + 120,
            "wires": []
        })
        add_node(flows, {
            "id": new_id(),
            "type": "ui_button",
            "z": virtual_tab_id,
            "name": f"V{even}",
            "group": group_id,
            "order": odd_toggle.get('order', 0) + 2,
            "width": 3, "height": 1,
            "passthru": False,
            "label": f"L{even} Toggle",
            "tooltip": "", "color": "", "bgcolor": "", "className": "", "icon": "",
            "payload": "click", "payloadType": "str",
            "topic": "", "topicType": "str",
            "x": 110, "y": v_base + 120,
            "wires": [[even_mqtt_out_id]]
        })
        add_node(flows, {
            "id": new_id(),
            "type": "ui_slider",
            "z": virtual_tab_id,
            "name": f"V{even} Brightness",
            "label": f"L{even} Brightness",
            "tooltip": "",
            "group": group_id,
            "order": odd_toggle.get('order', 0) + 3,
            "width": 3, "height": "",
            "passthru": True, "outs": "all",
            "topic": "", "topicType": "str",
            "min": 5, "max": 100, "step": 1,
            "className": "",
            "x": 100, "y": v_base + 160,
            "wires": [[even_func_id]]
        })
        add_node(flows, {
            "id": even_func_id,
            "type": "function",
            "z": virtual_tab_id,
            "name": "set_brightness",
            "func": "msg.payload = \"set_brightness \" + msg.payload;\nreturn msg;",
            "outputs": 1, "timeout": "", "noerr": 0, "initialize": "", "finalize": "", "libs": [],
            "x": 300, "y": v_base + 160,
            "wires": [[even_mqtt_out_id]]
        })

        # --- Physical ---
        odd_interpret = next((n for n in flows
                              if n.get('type') == 'function'
                              and n.get('z') == physical_tab_id
                              and 'Interpret' in n.get('name', '')
                              and f"L{odd}" in n.get('name', '')), None)
        if odd_interpret is None:
            print(f"  Warning: could not find Interpret node for L{odd}, skipping physical")
            continue
        p_base = odd_interpret['y']

        # Add even light's physical nodes at p_base + 80 / p_base + 120
        _add_physical_light(flows, device_id, even, broker_id, physical_tab_id, p_base + 80)

        print(f"  Pair L{odd}/L{even}: converted to single (L{even} nodes added, temp slider removed from L{odd})")



def remove_stale_wires(flows, removed_ids):
    for node in flows:
        if 'wires' not in node:
            continue
        node['wires'] = [
            [tid for tid in output if tid not in removed_ids]
            for output in node['wires']
        ]


def describe_change(count, old_val, new_val):
    lines = []
    if new_val > old_val:
        for i in range(old_val, new_val):
            even = count - i * 2
            odd = even - 1
            lines.append(f"  L{odd}/L{even}: single -> dual  (L{even} nodes removed, temp slider added to L{odd})")
    else:
        for i in range(new_val, old_val):
            even = count - i * 2
            odd = even - 1
            lines.append(f"  L{odd}/L{even}: dual -> single  (L{even} nodes restored, temp slider removed from L{odd})")
    return lines


def main():
    print("=== Ezama Light Board Configuration Tool ===\n")

    try:
        devices = discover_light_boards()

        if not devices:
            print("No light boards found. Make sure devices are online and MQTT broker is running.")
            sys.exit(1)

        device_ids = list(devices.keys())
        if len(device_ids) == 1:
            device_id = device_ids[0]
            print(f"Found device: {device_id}")
        else:
            print("Found devices:")
            for i, did in enumerate(device_ids, 1):
                d = devices[did]
                ip = d.get("ip", "?")
                count = d["lights"]["count"]
                dual = d["lights"]["dual_temp"]
                print(f"  {i}. {did} (ip: {ip}, lights: {count}, dual_temp: {dual})")
            while True:
                try:
                    choice = int(input("\nSelect device number: "))
                    if 1 <= choice <= len(device_ids):
                        device_id = device_ids[choice - 1]
                        break
                    else:
                        print(f"Please enter a number between 1 and {len(device_ids)}.")
                except ValueError:
                    print("Please enter a valid integer.")

        device = devices[device_id]
        light_count = device["lights"]["count"]
        max_dual = light_count // 2

        # Read current dual_temp from flows.json (what Node-RED currently has wired)
        flows = load_flows()
        old_val = read_current_dual_temp(flows, device_id)

        print(f"\nDevice: {device_id} | Lights: {light_count} | Current dual_temp (in Node-RED): {old_val} | Max: {max_dual}")

        while True:
            try:
                new_val = int(input(f"\nHow many dual temperature lights do you want (0-{max_dual})? "))
                if 0 <= new_val <= max_dual:
                    break
                else:
                    print(f"Please enter a number between 0 and {max_dual}.")
            except ValueError:
                print("Please enter a valid integer.")

        if new_val == old_val:
            print(f"\nNo change -- dual_temp is already {old_val} in Node-RED. Nothing to do.")
            sys.exit(0)

        change_lines = describe_change(light_count, old_val, new_val)

        print("\n" + "=" * 60)
        print("WARNING: This action will:")
        print(f"  * Send dual_temp={new_val} to {device_id} via MQTT")
        print(f"  * Surgically update only the affected light pairs in Node-RED:")
        for line in change_lines:
            print(line)
        print("  -> All other lights and devices are untouched")
        print("=" * 60)

        while True:
            confirm = input("\nDo you really want to proceed? (type 'yes' to continue): ").strip().lower()
            if confirm == "yes":
                break
            elif confirm in ["no", "n", ""]:
                print("Operation cancelled.")
                sys.exit(0)
            else:
                print("Please type 'yes' to confirm or anything else to cancel.")

        print("\nUpdating configuration...")

        print(f"Sending dual_temp={new_val} to {device_id}...")
        try:
            mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqttc.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqttc.publish(f"/lights/{device_id}/dual/command", str(new_val))
            mqttc.disconnect()
            print("MQTT command sent.")
            time.sleep(2)
        except Exception as e:
            print(f"Warning: Could not send MQTT command: {e}")

        print("Applying surgical Node-RED update...")
        if new_val > old_val:
            increase_dual_temp(flows, device_id, light_count, old_val, new_val)
        else:
            decrease_dual_temp(flows, device_id, light_count, old_val, new_val)

        backup_and_save_flows(flows)

        print("Restarting Node-RED service...")
        subprocess.run(["sudo", "systemctl", "restart", "nodered"], check=True)

        print("\nSuccess!")
        print(f"  * {device_id} dual_temp set to: {new_val}")
        print("  * Node-RED flows surgically updated -- other lights and devices untouched")

    except subprocess.CalledProcessError as e:
        print(f"Error executing system command: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
