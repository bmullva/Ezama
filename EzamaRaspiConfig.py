import re
import subprocess
import sys
import os
import time

def main():
    script_dir = "/home/pi/Ezama"
    script_name = "rpi_switch_light_mqtt2.py"
    file_path = os.path.join(script_dir, script_name)
    init_flows = "init_flows.json"
    flows_dest = os.path.expanduser("~/.node-red/flows.json")

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
        print("  • Overwrite the 'dual_temp' value in rpi_switch_light_mqtt2.py")
        print("  • Stop and restart the running rpi_switch_light_mqtt2.py script")
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

        # Update the Python file
        try:
            with open(file_path, 'r') as file:
                content = file.read()

            def replace_dual_temp(match):
                return f'{match.group(1)}{num_lights}'

            new_content = re.sub(r'("dual_temp"\s*:\s*)\d+', replace_dual_temp, content)

            if new_content == content:
                print("Warning: Could not find 'dual_temp' field in the file. No changes made.")
            else:
                with open(file_path, 'w') as file:
                    file.write(new_content)
                print(f"Successfully updated 'dual_temp' to {num_lights} in {file_path}")

        except FileNotFoundError:
            print(f"Error: File not found: {file_path}")
            sys.exit(1)
        except PermissionError:
            print(f"Error: Permission denied accessing {file_path}")
            sys.exit(1)

        # Stop any running instance of the script
        print("Stopping any running instance of rpi_switch_light_mqtt2.py...")
        subprocess.run(["pkill", "-f", script_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # Give it a moment to fully stop

        # Restart the script in the background
        print("Restarting rpi_switch_light_mqtt2.py...")
        log_file = os.path.join(script_dir, "mqtt_script.log")
        subprocess.Popen([
            "python3", script_name
        ], cwd=script_dir, stdout=open(log_file, 'a'), stderr=subprocess.STDOUT, start_new_session=True)

        print(f"Script restarted (logging to {log_file})")

        # Copy flows and restart Node-RED
        try:
            if not os.path.exists(init_flows):
                print(f"Error: {init_flows} not found in current directory.")
                sys.exit(1)

            print("Copying init_flows.json to Node-RED flows...")
            subprocess.run(["cp", init_flows, flows_dest], check=True)

            print("Restarting Node-RED service...")
            subprocess.run(["sudo", "systemctl", "restart", "nodered"], check=True)

            print("\nSuccess! Everything updated and restarted.")
            print(f"Dual temperature lights set to: {num_lights}")
            print("   • MQTT script is running with new configuration")
            print("   • Node-RED restarted with initial flows")

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