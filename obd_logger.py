import obd
import time
import datetime
import csv
import os
import sys
from collections import deque # Added for rolling averages
import numpy as np # For calculations like average, std dev

# Define Driving Style Categories
DRIVING_STYLE_PASSIVE = "Passive"
DRIVING_STYLE_MODERATE = "Moderate"
DRIVING_STYLE_AGGRESSIVE = "Aggressive"
DRIVING_STYLE_UNKNOWN = "UNKNOWN_STYLE"

# Define Road Type Categories
ROAD_TYPE_CITY = "City"
ROAD_TYPE_HIGHWAY = "Highway"
ROAD_TYPE_RURAL = "Rural" # Placeholder, might be harder to define
ROAD_TYPE_UNKNOWN = "UNKNOWN_ROAD"

# Define Traffic Condition Categories
TRAFFIC_CONDITION_LIGHT = "Light"
TRAFFIC_CONDITION_MODERATE = "Moderate"
TRAFFIC_CONDITION_HEAVY = "Heavy"
TRAFFIC_CONDITION_UNKNOWN = "UNKNOWN_TRAFFIC"

# Rolling Average Configuration
ROLLING_WINDOW_SIZE = 20  # Number of samples for rolling averages (e.g., 20 samples * 0.5s/sample = 10 seconds)
MIN_SAMPLES_FOR_CLASSIFICATION = 10 # Minimum samples needed before attempting classification

# Data storage for rolling averages
# We will store raw values and calculate averages/changes as needed.
# Using deque for efficient fixed-size lists
recent_rpm_values = deque(maxlen=ROLLING_WINDOW_SIZE)
recent_throttle_pos_values = deque(maxlen=ROLLING_WINDOW_SIZE)
recent_speed_values = deque(maxlen=ROLLING_WINDOW_SIZE)

# Helper function to calculate average from a deque
def get_average(dq, exclude_below=None):
    if not dq:
        return 0
    # Filter values if exclude_below is specified
    values = list(dq)
    if exclude_below is not None:
        values = [v for v in values if v > exclude_below]
    if not values: # If all values were filtered out
        return 0
    return np.mean(values)

# Helper function to calculate rate of change (average difference between consecutive elements)
def get_rate_of_change(dq):
    if len(dq) < 2:
        return 0
    # Calculate differences between consecutive elements
    # Use np.diff for simplicity if available, or manual loop
    diffs = np.diff(list(dq))
    return np.mean(diffs) if len(diffs) > 0 else 0

# Helper function to count near-zero speed occurrences (stops)
def count_stops(dq, stop_threshold=5): # Assuming speed in km/h, threshold for being "stopped"
    if not dq:
        return 0
    return sum(1 for speed in dq if speed < stop_threshold)

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
    print("Classifications (Style, Road, Traffic) will be determined automatically.")

    current_driving_style = DRIVING_STYLE_UNKNOWN
    current_road_type = ROAD_TYPE_UNKNOWN
    current_traffic_condition = TRAFFIC_CONDITION_UNKNOWN

    # Initialize deques for rolling data for this session
    # This ensures they are reset if main() were ever called multiple times (though not typical for this script)
    global recent_rpm_values, recent_throttle_pos_values, recent_speed_values
    recent_rpm_values.clear()
    recent_throttle_pos_values.clear()
    recent_speed_values.clear()

    BASE_LOG_INTERVAL = .4  # for high frequency data
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
            print("Attempting to connect via socat PTY /dev/ttys011...")
            connection = obd.OBD("/dev/ttys011", fast=True, timeout=30) # Auto-scan for USB/Bluetooth

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
            'road_type': current_road_type,
            'traffic_condition': current_traffic_condition
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
            header_names = ['timestamp', 'driving_style', 'road_type', 'traffic_condition'] + [pid.name for pid in ALL_PIDS_TO_LOG]
            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(CSV_FILENAME) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {CSV_FILENAME} with headers: {header_names}")

            if initial_log_entry: 
                writer.writerow(initial_log_entry)
                csvfile.flush()
                print(f"Logged initial full sample. Style: {current_driving_style}, Road: {current_road_type}, Traffic: {current_traffic_condition}.")
            
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
                
                log_entry = {
                    'timestamp': timestamp_iso,
                    'driving_style': current_driving_style,
                    'road_type': current_road_type,
                    'traffic_condition': current_traffic_condition
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

                current_rpm = current_pid_values.get(obd.commands.RPM.name)
                current_throttle_pos = current_pid_values.get(obd.commands.THROTTLE_POS.name)
                current_speed = current_pid_values.get(obd.commands.SPEED.name)

                if isinstance(current_rpm, (int, float)):
                    recent_rpm_values.append(current_rpm)
                if isinstance(current_throttle_pos, (int, float)):
                    recent_throttle_pos_values.append(current_throttle_pos)
                if isinstance(current_speed, (int, float)):
                    recent_speed_values.append(current_speed)

                # Call classification functions if enough data is available
                if len(recent_speed_values) >= MIN_SAMPLES_FOR_CLASSIFICATION: # Use speed deque length as a proxy for general data availability
                    current_driving_style = determine_driving_style(recent_rpm_values, recent_throttle_pos_values, recent_speed_values)
                    current_road_type = determine_road_type(recent_speed_values)
                    current_traffic_condition = determine_traffic_condition(recent_speed_values)
                else:
                    current_driving_style = DRIVING_STYLE_UNKNOWN
                    current_road_type = ROAD_TYPE_UNKNOWN
                    current_traffic_condition = TRAFFIC_CONDITION_UNKNOWN

                writer.writerow(log_entry)
                csvfile.flush()  

                log_count += 1
                if log_count % 10 == 0: 
                    status_msg = f"Logged entry {log_count} (Style: {current_driving_style}, Road: {current_road_type}, Traffic: {current_traffic_condition}): {timestamp_iso} - HF PIDs Read: {hf_reads}/{len(HIGH_FREQUENCY_PIDS)}"
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

def determine_driving_style(rpm_dq, throttle_dq, speed_dq):
    avg_rpm = get_average(rpm_dq)
    avg_throttle = get_average(throttle_dq)
    avg_moving_speed = get_average(speed_dq, exclude_below=0.1) 

    if avg_throttle > 50 or avg_rpm > 3500 and avg_moving_speed > 30: # heavy tuning required 
        return DRIVING_STYLE_AGGRESSIVE
    elif avg_throttle > 20 or avg_rpm > 2000:
        return DRIVING_STYLE_MODERATE
    else:
        return DRIVING_STYLE_PASSIVE

def determine_road_type(speed_dq, sustained_duration_samples=10, highway_speed_threshold=95, city_speed_upper_threshold=68, moving_speed_threshold=0.1):
    avg_moving_speed = get_average(speed_dq, exclude_below=moving_speed_threshold)
    
    if len(speed_dq) >= sustained_duration_samples:
        # For sustained speed check, we look at raw recent speeds, including brief slowdowns if mostly high speed.
        sustained_high_speed_count = sum(1 for speed in list(speed_dq)[-sustained_duration_samples:] if speed > highway_speed_threshold)
        if sustained_high_speed_count >= sustained_duration_samples * 0.7: 
            return ROAD_TYPE_HIGHWAY
    
    if avg_moving_speed > 0 and avg_moving_speed < city_speed_upper_threshold: # Must be moving to be considered for city speed
        return ROAD_TYPE_CITY 
    # If avg_moving_speed is 0 (e.g. prolonged stop but not enough for heavy traffic), or doesn't fit highway/city.
    return ROAD_TYPE_UNKNOWN # Default if not clearly highway or city based on moving speed

def determine_traffic_condition(speed_dq, stop_threshold=5, heavy_traffic_stop_freq=0.3, low_speed_heavy_traffic=20):
    avg_speed_inclusive_stops = get_average(speed_dq) # For traffic, overall average including stops is important
    num_stops = count_stops(speed_dq, stop_threshold)
    stop_frequency = num_stops / len(speed_dq) if len(speed_dq) > 0 else 0

    if stop_frequency >= heavy_traffic_stop_freq and avg_speed_inclusive_stops < low_speed_heavy_traffic:
        return TRAFFIC_CONDITION_HEAVY
    elif avg_speed_inclusive_stops < 40 or stop_frequency > 0.1: # Example thresholds
        return TRAFFIC_CONDITION_MODERATE
    else:
        return TRAFFIC_CONDITION_LIGHT

if __name__ == "__main__":
    main() 