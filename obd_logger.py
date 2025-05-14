import obd
import time
import datetime
import csv
import os
import sys
import select

# Define High-Frequency PIDs (polled every BASE_LOG_INTERVAL)
HIGH_FREQUENCY_PIDS = [
    obd.commands.RPM,
    obd.commands.THROTTLE_POS,
    obd.commands.SPEED,
]

# Define Low-Frequency PIDs (polled every 2 mins)
LOW_FREQUENCY_PIDS_POOL = [
    obd.commands.FUEL_PRESSURE,
    obd.commands.ENGINE_LOAD,
    obd.commands.COOLANT_TEMP,
    obd.commands.INTAKE_TEMP,
    obd.commands.TIMING_ADVANCE,
    obd.commands.MAF,
    obd.commands.INTAKE_PRESSURE, 
    obd.commands.SHORT_FUEL_TRIM_1,
    obd.commands.LONG_FUEL_TRIM_1,
    obd.commands.SHORT_FUEL_TRIM_2, 
    obd.commands.LONG_FUEL_TRIM_2,  
    obd.commands.COMMANDED_EQUIV_RATIO, 
    obd.commands.O2_B1S2, 
    obd.commands.O2_B2S2, 
    obd.commands.O2_S1_WR_VOLTAGE,
    obd.commands.COMMANDED_EGR,
]

ALL_PIDS_TO_LOG = HIGH_FREQUENCY_PIDS + LOW_FREQUENCY_PIDS_POOL

CSV_FILENAME_BASE = "obd_data_log" 
LOG_SUBDIRECTORY = "logs" 

WIFI_ADAPTER_HOST = "192.168.0.10"  
WIFI_ADAPTER_PORT = 35000           

WIFI_PROTOCOL = "6" 
USE_WIFI_SETTINGS = False # using socat to mimic serial connection

def get_pid_value(connection, pid_command):
    """Queries a PID and returns its value, or None if not available or error."""
    try:
        response = connection.query(pid_command, force=True)
        if response.is_null() or response.value is None:
            return None
        if hasattr(response.value, 'magnitude'):
            return response.value.magnitude
        return response.value
    except Exception as e:
        print(f"Error querying {pid_command.name}: {e}") 
        return None
    
def main():
    connection = None
    print("Starting OBD-II Data Logger...")
    print("You can type 'style <description>' or 'road <description>' and press Enter to label logs.")
    print("Example: 'style aggressive' or 'road highway'")
    print("Initial classifications are 'UNKNOWN_STYLE' and 'UNKNOWN_ROAD'.")

    current_driving_style = "UNKNOWN_STYLE"
    current_road_type = "UNKNOWN_ROAD"

    BASE_LOG_INTERVAL = .5  # for high frequency data
    LOW_FREQUENCY_GROUP_POLL_INTERVAL = 45.0  # Interval in seconds to poll one group of LF PIDs 
    NUM_LOW_FREQUENCY_GROUPS = 3

    # Prepare Low-Frequency PID groups
    low_frequency_pid_groups = []
    if LOW_FREQUENCY_PIDS_POOL: 
        chunk_size = (len(LOW_FREQUENCY_PIDS_POOL) + NUM_LOW_FREQUENCY_GROUPS - 1) // NUM_LOW_FREQUENCY_GROUPS
        for i in range(0, len(LOW_FREQUENCY_PIDS_POOL), chunk_size):
            low_frequency_pid_groups.append(LOW_FREQUENCY_PIDS_POOL[i:i + chunk_size])
    
    if not low_frequency_pid_groups: # Handle case with no LF PIDs
        low_frequency_pid_groups.append([])
        NUM_LOW_FREQUENCY_GROUPS = 1 

    last_low_frequency_group_poll_time = time.monotonic() 
    current_low_frequency_group_index = 0
    
    current_pid_values = {pid.name: '' for pid in ALL_PIDS_TO_LOG} 

    log_dir_path = os.path.join(os.getcwd(), LOG_SUBDIRECTORY)

    try:
        os.makedirs(log_dir_path, exist_ok=True)
        print(f"Logs saved in: {log_dir_path}")
    except OSError as e:
        print(f"Error creating directory {log_dir_path}: {e}")
        print("Log files will be saved in the current working directory instead.")
        log_dir_path = os.getcwd() 

    current_session_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file_name_only = f"{CSV_FILENAME_BASE}_{current_session_timestamp}.csv"
    CSV_FILENAME = os.path.join(log_dir_path, csv_file_name_only)

    try:
        if USE_WIFI_SETTINGS:
            print(f"Attempting to connect to WiFi adapter at {WIFI_ADAPTER_HOST}:{WIFI_ADAPTER_PORT} using protocol {WIFI_PROTOCOL}...")
            connection = obd.OBD(protocol=WIFI_PROTOCOL, 
                                 host=WIFI_ADAPTER_HOST, 
                                 port=WIFI_ADAPTER_PORT, 
                                 fast=False,
                                 timeout=30) 
        else:
            print("Attempting to connect via socat PTY /dev/ttys030...")
            connection = obd.OBD("/dev/ttys034", fast=True, timeout=30) # Auto-scan for USB/Bluetooth

        if not connection.is_connected():
            print("Failed to connect to OBD-II adapter.")
            print(f"Connection status: {connection.status()}")
            return
        
        print(f"Successfully connected to OBD-II adapter: {connection.port_name()}")
        print(f"Adapter status: {connection.status()}")
        print(f"Supported PIDs (sample):")
        supported_commands = connection.supported_commands
        for i, cmd in enumerate(supported_commands):
            print(f"  - {cmd.name}")
        if not supported_commands:
            print("No commands")

        # Creating initial full PID sample to have fully populated rows from beginning 
        print("\nPerforming initial full PID sample...")
        initial_log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'driving_style': current_driving_style,
            'road_type': current_road_type
        }
        
        print("Polling initial High-Frequency PIDs...")
        for pid_command in HIGH_FREQUENCY_PIDS:
            value = get_pid_value(connection, pid_command)
            current_pid_values[pid_command.name] = value if value is not None else ''
            initial_log_entry[pid_command.name] = current_pid_values[pid_command.name]

        print("Polling initial Low-Frequency PIDs (all groups)...")
        if low_frequency_pid_groups and low_frequency_pid_groups[0]: # Check if there are any LF PIDs
            for group in low_frequency_pid_groups:
                for pid_command in group:
                    value = get_pid_value(connection, pid_command)
                    current_pid_values[pid_command.name] = value if value is not None else ''
                    initial_log_entry[pid_command.name] = current_pid_values[pid_command.name]
        else:
            print("No Low-Frequency PIDs to poll for initial sample.")

        for pid_obj in ALL_PIDS_TO_LOG:
            if pid_obj.name not in initial_log_entry:
                initial_log_entry[pid_obj.name] = '' # Default to empty if somehow missed

    except Exception as e:
        print(f"An error occurred during connection or initial PID sample: {e}")
        if connection and connection.is_connected():
            connection.close()
        return

    file_exists = os.path.isfile(CSV_FILENAME)
    try:
        with open(CSV_FILENAME, 'a', newline='') as csvfile:
            header_names = ['timestamp', 'driving_style', 'road_type'] + [pid.name for pid in ALL_PIDS_TO_LOG]
            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(CSV_FILENAME) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {CSV_FILENAME} with headers: {header_names}")

            if initial_log_entry: 
                writer.writerow(initial_log_entry)
                csvfile.flush()
                print(f"Logged initial full sample. Style: {current_driving_style}, Road: {current_road_type}.")
            
            # Reset LF poll timer to start 2-min delay AFTER initial full sample
            last_low_frequency_group_poll_time = time.monotonic()
            current_low_frequency_group_index = 0 

            print(f"\nLogging high-frequency data every {BASE_LOG_INTERVAL} second(s).")
            print(f"Polling one group of low-frequency PIDs every {LOW_FREQUENCY_GROUP_POLL_INTERVAL} second(s).")
            print(f"Low-frequency PIDs divided into {len(low_frequency_pid_groups)} groups.")
            
            log_count = 0
            while True:
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    raw_input = sys.stdin.readline().strip()
                    if raw_input: # Only process if the input is not empty
                        parts = raw_input.lower().split(maxsplit=1)
                        command = parts[0]
                        value = parts[1] if len(parts) > 1 else ""

                        if command == "style":
                            if value:
                                current_driving_style = raw_input[len("style "):].strip() # Preserve case from original input after command
                                print(f"\nDriving style updated to: {current_driving_style}\n")
                            else:
                                print("\nUsage: style <description>\n")
                        elif command == "road":
                            if value:
                                current_road_type = raw_input[len("road "):].strip() # Preserve case from original input after command
                                print(f"\nRoad type updated to: {current_road_type}\n")
                            else:
                                print("\nUsage: road <description>\n")
                        else:
                            print(f"\nUnknown command '{command}'. Use 'style <desc>' or 'road <desc>'. \n")

                loop_start_time = time.monotonic()
                current_datetime = datetime.datetime.now()
                timestamp_iso = current_datetime.isoformat()
                
                log_entry = {
                    'timestamp': timestamp_iso,
                    'driving_style': current_driving_style,
                    'road_type': current_road_type
                }
                for pid_name in current_pid_values: # Initialize with last known values
                    log_entry[pid_name] = current_pid_values[pid_name]

                hf_reads = 0
                # 1. Poll High-Frequency PIDs
                for pid_command in HIGH_FREQUENCY_PIDS:
                    value = get_pid_value(connection, pid_command)
                    current_pid_values[pid_command.name] = value if value is not None else ''
                    log_entry[pid_command.name] = current_pid_values[pid_command.name]
                    if value is not None:
                        hf_reads += 1

                lf_reads_this_cycle = 0
                lf_group_polled_this_cycle = "None"
                # 2. Check and Poll Low-Frequency PID Group
                if low_frequency_pid_groups and (time.monotonic() - last_low_frequency_group_poll_time) >= LOW_FREQUENCY_GROUP_POLL_INTERVAL:
                    group_to_poll = low_frequency_pid_groups[current_low_frequency_group_index]
                    lf_group_polled_this_cycle = f"Group {current_low_frequency_group_index + 1}/{len(low_frequency_pid_groups)}"
                   
                    for pid_command in group_to_poll:
                        value = get_pid_value(connection, pid_command)
                        current_pid_values[pid_command.name] = value if value is not None else ''
                        log_entry[pid_command.name] = current_pid_values[pid_command.name]
                        if value is not None:
                            lf_reads_this_cycle +=1 
                        else: 
                            print(f"Warning: Could not read LF PID {pid_command.name}")
                    
                    last_low_frequency_group_poll_time = time.monotonic()
                    current_low_frequency_group_index = (current_low_frequency_group_index + 1) % len(low_frequency_pid_groups)

                writer.writerow(log_entry)
                csvfile.flush()  

                log_count += 1
                if log_count % 10 == 0: 
                    status_msg = f"Logged entry {log_count} (Style: {current_driving_style}, Road: {current_road_type}): {timestamp_iso} - HF PIDs Read: {hf_reads}/{len(HIGH_FREQUENCY_PIDS)}"
                    if lf_reads_this_cycle > 0 or lf_group_polled_this_cycle != "None":
                         status_msg += f" - LF PIDs ({lf_group_polled_this_cycle}) Read: {lf_reads_this_cycle}/unknown_total_for_group_easily"
                    print(status_msg)
                
                elapsed_time_in_loop = time.monotonic() - loop_start_time
                sleep_duration = max(0, BASE_LOG_INTERVAL - elapsed_time_in_loop)
                time.sleep(sleep_duration)

    except KeyboardInterrupt:
        print("\nStopping data logging due to user interruption (Ctrl+C).")
    except Exception as e:
        print(f"An error occurred during logging: {e}")
    finally:
        if connection and connection.is_connected():
            print("Closing OBD-II connection.")
            connection.close()
        print(f"Data logging stopped. CSV file '{CSV_FILENAME}' saved.")

if __name__ == "__main__":
    main() 