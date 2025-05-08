import obd
import time
import datetime
import csv
import os

# --- Configuration ---
LOG_INTERVAL_SECONDS = .2  # How often to log data (in seconds)
# Common PIDs to start with. Add or remove as needed.
# You can find more PIDs in the obd.commands documentation or by querying supported commands.

# Define High-Frequency PIDs (polled every BASE_LOG_INTERVAL)
HIGH_FREQUENCY_PIDS = [
    obd.commands.RPM,
    obd.commands.THROTTLE_POS,
    obd.commands.FUEL_PRESSURE,
    obd.commands.SPEED,
]

# Define Low-Frequency PIDs (polled in groups less often)
# These are the remaining PIDs from your previous list, respecting commented out ones
LOW_FREQUENCY_PIDS_POOL = [
    obd.commands.ENGINE_LOAD,
    obd.commands.ABSOLUTE_LOAD,
    obd.commands.COOLANT_TEMP,
    obd.commands.INTAKE_TEMP,
    obd.commands.AMBIENT_AIR_TEMP,
    obd.commands.OIL_TEMP,
    obd.commands.TIMING_ADVANCE,
    obd.commands.MAF,
    obd.commands.INTAKE_PRESSURE, 
    obd.commands.BAROMETRIC_PRESSURE,
    obd.commands.RUN_TIME,
    obd.commands.CONTROL_MODULE_VOLTAGE,
    obd.commands.RELATIVE_THROTTLE_POS,
    obd.commands.THROTTLE_POS_B, 
    obd.commands.RELATIVE_ACCEL_POS,
    obd.commands.FUEL_LEVEL,
    obd.commands.FUEL_STATUS,
    obd.commands.FUEL_RAIL_PRESSURE_VAC,
    obd.commands.FUEL_RAIL_PRESSURE_DIRECT,
    obd.commands.FUEL_RAIL_PRESSURE_ABS,
    obd.commands.SHORT_FUEL_TRIM_1,
    obd.commands.LONG_FUEL_TRIM_1,
    obd.commands.SHORT_FUEL_TRIM_2, 
    obd.commands.LONG_FUEL_TRIM_2,  
    obd.commands.COMMANDED_EQUIV_RATIO, 
    obd.commands.FUEL_TYPE,
    obd.commands.ETHANOL_PERCENT,
    obd.commands.O2_SENSORS, 
    obd.commands.O2_B1S1, 
    obd.commands.O2_B1S2, 
    obd.commands.O2_B2S1, 
    obd.commands.O2_B2S2, 
    obd.commands.O2_S1_WR_VOLTAGE,
    obd.commands.O2_S1_WR_CURRENT,
    obd.commands.COMMANDED_EGR,
    obd.commands.EGR_ERROR,
    obd.commands.EVAP_VAPOR_PRESSURE,
    obd.commands.CATALYST_TEMP_B1S1,
    obd.commands.CATALYST_TEMP_B1S2,
    obd.commands.STATUS, 
    obd.commands.DISTANCE_W_MIL,
    obd.commands.DISTANCE_SINCE_DTC_CLEAR,
    obd.commands.TIME_SINCE_DTC_CLEARED,
    obd.commands.WARMUPS_SINCE_DTC_CLEAR,
    obd.commands.OBD_COMPLIANCE,
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

    BASE_LOG_INTERVAL = 1.5  # for high frequency data
    LOW_FREQUENCY_GROUP_POLL_INTERVAL = 120.0  # Interval in seconds to poll one group of LF PIDs (2 minutes)
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
            print("Attempting to connect via socat PTY /dev/ttys010...")
            connection = obd.OBD("/dev/ttys010", fast=False, timeout=30) # Auto-scan for USB/Bluetooth

        if not connection.is_connected():
            print("Failed to connect to OBD-II adapter.")
            print(f"Connection status: {connection.status()}")
            return
        
        print(f"Successfully connected to OBD-II adapter: {connection.port_name()}")
        print(f"Adapter status: {connection.status()}")
        print(f"Supported PIDs (sample):")
        supported_commands = connection.supported_commands
        for i, cmd in enumerate(supported_commands):
            if i < 10: # Print first 10 supported PIDs
                 print(f"  - {cmd.name}")
            else:
                print(f"  ... and {len(supported_commands) - 10} more.")
                break
        if not supported_commands:
            print("No commands")

        # Creating initial full PID sample to have fully populated rows from beginning 
        print("\nPerforming initial full PID sample...")
        initial_log_entry = {'timestamp': datetime.datetime.now().isoformat()}
        
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
            header_names = ['timestamp'] + [pid.name for pid in ALL_PIDS_TO_LOG]
            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(CSV_FILENAME) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {CSV_FILENAME} with headers: {header_names}")

            if initial_log_entry: 
                writer.writerow(initial_log_entry)
                csvfile.flush()
                log_count = 0
                print(f"Logged initial full sample as entry {log_count}.")
            
            # Reset LF poll timer to start 2-min delay AFTER initial full sample
            last_low_frequency_group_poll_time = time.monotonic()
            current_low_frequency_group_index = 0 

            print(f"\nLogging high-frequency data every {BASE_LOG_INTERVAL} second(s).")
            print(f"Polling one group of low-frequency PIDs every {LOW_FREQUENCY_GROUP_POLL_INTERVAL} second(s).")
            print(f"Low-frequency PIDs divided into {len(low_frequency_pid_groups)} groups.")
            
            log_count = 0
            while True:
                loop_start_time = time.monotonic()
                current_datetime = datetime.datetime.now()
                timestamp_iso = current_datetime.isoformat()
                
                log_entry = {'timestamp': timestamp_iso}
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
                    status_msg = f"Logged entry {log_count}: {timestamp_iso} - HF PIDs Read: {hf_reads}/{len(HIGH_FREQUENCY_PIDS)}"
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