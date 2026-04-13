import subprocess
import sys
import os
import time
import paho.mqtt.client as mqtt

def main():
    init_flows = "/home/pi/Ezama/clean/init_flows.json"
    flows_dest = os.path.expanduser("~/.node-red/flows.json")
    device_id = "RPi1"

    print("=== Dual Temperature Lights Configuration Tool ===\n")

    try:
        # Ask for number of dual temperature lights
        while True:
            try:
                num_lights = int(input("How many dual temperature lights do you want (0-6)? "))
                if 0 <= num_lights <= 6:
                    break
                else:
                    print("Please enter a number between 0 and 6.")
            except ValueError:
                print("Please enter a valid integer.")

        print(f"\nYou selected: {num_lights} dual temperature light(s).")

        # Strong warning
        print("\n" + "="*60)
        print("WARNING: This action will:")
        print(f"  • Send dual_temp={num_lights} to rpi_switch_light_mqtt2.py via MQTT")
        print("  • Replace your current Node-RED flows with init_flows.json")
        print("  • Restart the Node-RED service")
        print("  → ALL CURRENT NODE-RED CONFIGURATIONS WILL BE LOST!")
        print("="*60)

        # Confirmation
        while True:
            confirm = input("\nDo you really want to proceed? (type 'yes' to continue): ").strip().lower()
            if confirm == 'yes':
                break
            elif confirm in ['no', 'n', '']:
                print("Operation cancelled.")
                sys.exit(0)
            else:
                print("Please type 'yes' to confirm or anything else to cancel.")

        print("\nUpdating configuration...")

        # Send dual_temp update via MQTT
        print(f"Sending dual_temp={num_lights} to rpi_switch_light_mqtt2.py via MQTT...")
        try:
            mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqttc.connect("127.0.0.1", 1883, 60)
            mqttc.publish(f"/lights/{device_id}/dual/command", str(num_lights))
            mqttc.disconnect()
            print("MQTT command sent.")
            time.sleep(2)  # Give the script time to process and persist
        except Exception as e:
            print(f"Warning: Could not send MQTT command: {e}")
            print("The running script may not have been updated — restart it manually if needed.")

        # Copy flows and restart Node-RED
        try:
            if not os.path.exists(init_flows):
                print(f"Error: {init_flows} not found.")
                sys.exit(1)

            print("Copying init_flows.json to Node-RED flows...")
            subprocess.run(["cp", init_flows, flows_dest], check=True)

            print("Restarting Node-RED service...")
            subprocess.run(["sudo", "systemctl", "restart", "nodered"], check=True)

            print("\nSuccess!")
            print(f"  • Dual temperature lights set to: {num_lights}")
            print("  • Node-RED restarted with initial flows")

        except subprocess.CalledProcessError as e:
            print(f"Error executing system command: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error during copy/restart: {e}")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
