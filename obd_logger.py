import obd
import time
import datetime
import csv
import os
from collections import deque 
import numpy as np 

DRIVING_STYLE_PASSIVE = "Passive"
DRIVING_STYLE_MODERATE = "Moderate"
DRIVING_STYLE_AGGRESSIVE = "Aggressive"
DRIVING_STYLE_UNKNOWN = "UNKNOWN_STYLE"

ROAD_TYPE_LOCAL = "Local"
ROAD_TYPE_MAIN = "Main"
ROAD_TYPE_HIGHWAY = "Highway"
ROAD_TYPE_UNKNOWN = "UNKNOWN_ROAD"

TRAFFIC_CONDITION_LIGHT = "Light"
TRAFFIC_CONDITION_MODERATE = "Moderate"
TRAFFIC_CONDITION_HEAVY = "Heavy"
TRAFFIC_CONDITION_UNKNOWN = "UNKNOWN_TRAFFIC"

# Rolling Average Configuration
ROLLING_WINDOW_SIZE = 20  # 6 seconds
MIN_SAMPLES_FOR_CLASSIFICATION = 10 

# ROC needs tuning
SHORT_ROC_WINDOW_SIZE = 3  
MIN_SAMPLES_FOR_ROC_CHECK = SHORT_ROC_WINDOW_SIZE 
ROC_THROTTLE_AGGRESSIVE_THRESHOLD = 30.0  
ROC_RPM_AGGRESSIVE_THRESHOLD = 800.0      
ROC_SPEED_AGGRESSIVE_THRESHOLD = 10.0     
MIN_RPM_FOR_AGGRESSIVE_TRIGGER = 1700.0   
AGGRESSIVE_EVENT_COOLDOWN_SAMPLES = 12    

recent_rpm_values = deque(maxlen=ROLLING_WINDOW_SIZE)
recent_throttle_pos_values = deque(maxlen=ROLLING_WINDOW_SIZE)
recent_speed_values = deque(maxlen=ROLLING_WINDOW_SIZE)

# Helper function to calculate average from a deque
def get_average(dq, exclude_below=None):
    if not dq:
        return 0
    values = list(dq)
    if exclude_below is not None:
        values = [v for v in values if v > exclude_below]
    if not values: # If all values were filtered out
        return 0
    return np.mean(values)

def get_rate_of_change(dq):
    if len(dq) < 2:
        return 0
    # Calculate differences between consecutive elements
    # Use np.diff for simplicity if available, or manual loop
    diffs = np.diff(list(dq))
    return np.mean(diffs) if len(diffs) > 0 else 0

def count_stops(dq, stop_threshold=5): # Assuming speed in km/h, threshold for being "stopped"
    if not dq:
        return 0
    return sum(1 for speed in dq if speed < stop_threshold)

HIGH_FREQUENCY_PIDS = [
    obd.commands.RPM,
    obd.commands.THROTTLE_POS,
    obd.commands.SPEED,
]

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
    aggressive_event_cooldown_remaining = 0 

    global recent_rpm_values, recent_throttle_pos_values, recent_speed_values
    recent_rpm_values.clear()
    recent_throttle_pos_values.clear()
    recent_speed_values.clear()

    BASE_LOG_INTERVAL = .3  # for high frequency data
    LOW_FREQUENCY_GROUP_POLL_INTERVAL = 60.0  # Interval in seconds to poll one group of LF PIDs 
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
                
                if aggressive_event_cooldown_remaining > 0:
                    aggressive_event_cooldown_remaining -= 1

                # 2. Poll PIDs (High Frequency)
                hf_reads = 0
                for pid_command in HIGH_FREQUENCY_PIDS:
                    value = get_pid_value(connection, pid_command)
                    current_pid_values[pid_command.name] = value if value is not None else ''
                    if value is not None:
                        hf_reads += 1
                
                lf_reads_this_cycle = 0
                lf_group_polled_this_cycle = "None"
                if low_frequency_pid_groups and (time.monotonic() - last_low_frequency_group_poll_time) >= LOW_FREQUENCY_GROUP_POLL_INTERVAL:
                    group_to_poll = low_frequency_pid_groups[current_low_frequency_group_index]
                    lf_group_polled_this_cycle = f"Group {current_low_frequency_group_index + 1}/{len(low_frequency_pid_groups)}"
                   
                    for pid_command in group_to_poll:
                        value = get_pid_value(connection, pid_command)
                        current_pid_values[pid_command.name] = value if value is not None else ''
                        if value is not None:
                            lf_reads_this_cycle +=1 
                        else: 
                            print(f"Warning: Could not read LF PID {pid_command.name}")
                    
                    last_low_frequency_group_poll_time = time.monotonic()
                    current_low_frequency_group_index = (current_low_frequency_group_index + 1) % len(low_frequency_pid_groups)

                current_rpm_val = current_pid_values.get(obd.commands.RPM.name)
                current_throttle_pos_val = current_pid_values.get(obd.commands.THROTTLE_POS.name)
                current_speed_val = current_pid_values.get(obd.commands.SPEED.name)

                if isinstance(current_rpm_val, (int, float)):
                    recent_rpm_values.append(current_rpm_val)
                if isinstance(current_throttle_pos_val, (int, float)):
                    recent_throttle_pos_values.append(current_throttle_pos_val)
                if isinstance(current_speed_val, (int, float)):
                    recent_speed_values.append(current_speed_val)

                if len(recent_speed_values) >= MIN_SAMPLES_FOR_CLASSIFICATION: 
                    current_driving_style, aggressive_event_cooldown_remaining = determine_driving_style(
                        recent_rpm_values, 
                        recent_throttle_pos_values, 
                        recent_speed_values,
                        aggressive_event_cooldown_remaining 
                    )
                    current_road_type = determine_road_type(recent_speed_values)
                    current_traffic_condition = determine_traffic_condition(recent_speed_values)
                else:
                    current_driving_style = DRIVING_STYLE_UNKNOWN
                    current_road_type = ROAD_TYPE_UNKNOWN
                    current_traffic_condition = TRAFFIC_CONDITION_UNKNOWN

                final_log_entry = {
                    'timestamp': timestamp_iso,
                    'driving_style': current_driving_style,
                    'road_type': current_road_type,
                    'traffic_condition': current_traffic_condition
                }
                # Add all PID values for this cycle from current_pid_values
                for pid_obj in ALL_PIDS_TO_LOG:
                     final_log_entry[pid_obj.name] = current_pid_values.get(pid_obj.name, '')

                writer.writerow(final_log_entry)
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

def determine_driving_style(rpm_dq, throttle_dq, speed_dq, current_aggressive_cooldown):
    # If already in an aggressive event cooldown, maintain style and let cooldown be managed by main loop
    if current_aggressive_cooldown > 0:
        return DRIVING_STYLE_AGGRESSIVE, current_aggressive_cooldown

    # --- Aggressive Event Detection using Rate of Change (RoC) ---
    if len(throttle_dq) >= SHORT_ROC_WINDOW_SIZE and \
       len(rpm_dq) >= SHORT_ROC_WINDOW_SIZE and \
       len(speed_dq) >= SHORT_ROC_WINDOW_SIZE:

        # Get short recent history for RoC calculation
        short_throttle_list = list(throttle_dq)[-SHORT_ROC_WINDOW_SIZE:]
        short_rpm_list = list(rpm_dq)[-SHORT_ROC_WINDOW_SIZE:]
        short_speed_list = list(speed_dq)[-SHORT_ROC_WINDOW_SIZE:]

        # Calculate RoC for each parameter over the short window
        roc_throttle = short_throttle_list[-1] - short_throttle_list[0]
        roc_rpm = short_rpm_list[-1] - short_rpm_list[0]
        roc_speed = short_speed_list[-1] - short_speed_list[0]
        
        avg_rpm_short_window = get_average(deque(short_rpm_list)) # Use deque for get_average compatibility

        # Check for aggressive conditions based on RoC
        is_aggressive_roc = (
            roc_throttle >= ROC_THROTTLE_AGGRESSIVE_THRESHOLD and
            roc_rpm >= ROC_RPM_AGGRESSIVE_THRESHOLD and
            roc_speed >= ROC_SPEED_AGGRESSIVE_THRESHOLD and # Ensuring positive RoC (acceleration)
            avg_rpm_short_window >= MIN_RPM_FOR_AGGRESSIVE_TRIGGER
        )

        if is_aggressive_roc:
            return DRIVING_STYLE_AGGRESSIVE, AGGRESSIVE_EVENT_COOLDOWN_SAMPLES # Start cooldown

    avg_rpm_long = get_average(rpm_dq)
    avg_throttle_long = get_average(throttle_dq)

    # User-tuned thresholds for moderate, from previous state of file
    if avg_throttle_long > 20 or avg_rpm_long > 2000:
        return DRIVING_STYLE_MODERATE, 0 
    else:
        return DRIVING_STYLE_PASSIVE, 0

def determine_road_type(speed_dq, sustained_duration_samples=10, highway_speed_threshold=88, city_speed_upper_threshold=55, moving_speed_threshold=0.1):
    avg_moving_speed = get_average(speed_dq, exclude_below=moving_speed_threshold)
    
    if len(speed_dq) >= sustained_duration_samples:
        sustained_high_speed_count = sum(1 for speed in list(speed_dq)[-sustained_duration_samples:] if speed > highway_speed_threshold)
        if sustained_high_speed_count >= sustained_duration_samples * 0.7: 
            return ROAD_TYPE_HIGHWAY
    
    if avg_moving_speed > 0 and avg_moving_speed < city_speed_upper_threshold: # must be moving
        return ROAD_TYPE_LOCAL 
    
    if avg_moving_speed > city_speed_upper_threshold and avg_moving_speed < highway_speed_threshold:
        return ROAD_TYPE_MAIN
    return ROAD_TYPE_UNKNOWN 

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