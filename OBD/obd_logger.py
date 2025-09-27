import obd
import time
import datetime
import csv
import os
from collections import deque 
import numpy as np 
import shutil
import subprocess

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
ROC_THROTTLE_AGGRESSIVE_THRESHOLD = 25.0  
ROC_RPM_AGGRESSIVE_THRESHOLD = 700.0      
ROC_SPEED_AGGRESSIVE_THRESHOLD = 8.0     
MIN_RPM_FOR_AGGRESSIVE_TRIGGER = 1000.0   
AGGRESSIVE_EVENT_COOLDOWN_SAMPLES = 15    

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
# Define new structured log directories relative to the OBD_Logger/OBD directory
LOGS_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs") # Corrected: Up two levels to Base, then into logs
ORIGINAL_CSV_DIR = os.path.join(LOGS_BASE_DIR, "OriginalCSV")
DUPLICATE_CSV_DIR = os.path.join(LOGS_BASE_DIR, "DuplicateCSV")

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
    
def perform_logging_session():
    connection = None
    print("Starting OBD-II Data Logger...")
    print("Classifications (Style, Road, Traffic) will be determined automatically.")

   
    initial_driving_style = "" 
    initial_road_type = ""
    initial_traffic_condition = ""
    
    BASE_LOG_INTERVAL = .3  # for high frequency data
    LOW_FREQUENCY_GROUP_POLL_INTERVAL = 90.0  # Interval in seconds to poll one group of LF PIDs 
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

    # Create log directories
    for dir_path in [ORIGINAL_CSV_DIR, DUPLICATE_CSV_DIR]: # Add ANALYZED_OUTPUT_DIR if used
        try:
            os.makedirs(dir_path, exist_ok=True)
            print(f"Ensured directory exists: {dir_path}")
        except OSError as e:
            print(f"Error creating directory {dir_path}: {e}. Attempting to use current directory.")
            # Fallback logic may be needed if creation fails critically
            if dir_path == ORIGINAL_CSV_DIR: # Critical for saving original log
                 print("Cannot create original log directory. Exiting.")
                 return None 

    current_session_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file_name_only = f"{CSV_FILENAME_BASE}_{current_session_timestamp}.csv"
    original_csv_filepath = os.path.join(ORIGINAL_CSV_DIR, csv_file_name_only)

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
            connection = obd.OBD("/dev/ttys086", fast=True, timeout=30) # Auto-scan for USB/Bluetooth

        if not connection.is_connected():
            print("Failed to connect to OBD-II adapter.")
            print(f"Connection status: {connection.status()}")
            return None
        
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
            'driving_style': initial_driving_style,
            'road_type': initial_road_type,
            'traffic_condition': initial_traffic_condition
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
        return None

    file_exists = os.path.isfile(original_csv_filepath)
    try:
        with open(original_csv_filepath, 'a', newline='') as csvfile:
            # Add new columns for analyzer output, they will be empty initially from logger
            header_names = ['timestamp', 
                            'driving_style', 'road_type', 'traffic_condition', # Original placeholder columns
                            'driving_style_analyzed', 'road_type_analyzed', 'traffic_condition_analyzed' # For analyzer
                           ] + [pid.name for pid in ALL_PIDS_TO_LOG]
            
            # Remove duplicates if any PID name is already in the first part
            processed_headers = []
            for item in header_names:
                if item not in processed_headers:
                    processed_headers.append(item)
            header_names = processed_headers

            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(original_csv_filepath) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {original_csv_filepath} with headers: {header_names}")

            if initial_log_entry: 
                # Add placeholder columns for analyzer to the initial entry
                initial_log_entry['driving_style_analyzed'] = ''
                initial_log_entry['road_type_analyzed'] = ''
                initial_log_entry['traffic_condition_analyzed'] = ''
                writer.writerow(initial_log_entry)
                csvfile.flush()
                print(f"Logged initial full sample. Style: {initial_driving_style}, Road: {initial_road_type}, Traffic: {initial_traffic_condition}.")
            
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


                final_log_entry = {
                    'timestamp': timestamp_iso,
                    'driving_style': initial_driving_style,
                    'road_type': initial_road_type,
                    'traffic_condition': initial_traffic_condition,
                    'driving_style_analyzed': '',
                    'road_type_analyzed': '',
                    'traffic_condition_analyzed': ''
                }
                # Add all PID values for this cycle from current_pid_values
                for pid_obj in ALL_PIDS_TO_LOG:
                     final_log_entry[pid_obj.name] = current_pid_values.get(pid_obj.name, '')

                writer.writerow(final_log_entry)
                csvfile.flush()  

                log_count += 1
                if log_count % 10 == 0: 
                    status_msg = f"Logged entry {log_count} - HF PIDs Read: {hf_reads}/{len(HIGH_FREQUENCY_PIDS)}"
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
        print(f"Data logging stopped. Original CSV file '{original_csv_filepath}' saved.")

    return original_csv_filepath

def duplicate_csv(original_filepath):
    if not original_filepath or not os.path.exists(original_filepath):
        print(f"Error: Original CSV not found for duplication: {original_filepath}")
        return None
    
    # Ensure DUPLICATE_CSV_DIR exists (it should have been created by perform_logging_session)
    os.makedirs(DUPLICATE_CSV_DIR, exist_ok=True)
    
    # Get just the filename from the original path
    original_filename = os.path.basename(original_filepath)
    base, ext = os.path.splitext(original_filename)
    
    # Construct new filename for the duplicate
    duplicate_filename = f"{base}_to_analyze{ext}" # Suffix to distinguish
    duplicate_filepath = os.path.join(DUPLICATE_CSV_DIR, duplicate_filename)
    
    try:
        shutil.copy2(original_filepath, duplicate_filepath)
        print(f"Successfully duplicated CSV to: {duplicate_filepath}")
        return duplicate_filepath
    except Exception as e:
        print(f"Error duplicating CSV {original_filepath} to {duplicate_filepath}: {e}")
        return None

def run_analyzer_on_csv(csv_to_analyze_path):
    if not csv_to_analyze_path or not os.path.exists(csv_to_analyze_path):
        print(f"Error: Analyzer input CSV not found: {csv_to_analyze_path}")
        return

    # Analyzer script is in the same directory as this logger script
    analyzer_script_path = os.path.join(os.path.dirname(__file__), "obd_analyzer.py") 
    
    if not os.path.exists(analyzer_script_path):
        print(f"CRITICAL Error: Analyzer script not found at {analyzer_script_path}")
        return

    analyzed_file_basename = os.path.basename(csv_to_analyze_path).replace("_to_analyze.csv", "_final_analyzed.csv")
    final_output_path = os.path.join(DUPLICATE_CSV_DIR, analyzed_file_basename)

    command = [
        "python",
        analyzer_script_path,
        csv_to_analyze_path, 
        "--output_csv",
        final_output_path   
    ]
    
    print(f"Running analyzer: {' '.join(command)}")
    try:
        process = subprocess.run(command, check=True, capture_output=True, text=True, cwd=os.path.dirname(__file__))
        print("Analyzer Output:\n", process.stdout)
        if process.stderr: print("Analyzer Errors:\n", process.stderr)
        print(f"Analyzer finished. Output saved to {final_output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error running analyzer: {e}\nStdout: {e.stdout}\nStderr: {e.stderr}")
    except FileNotFoundError:
        print(f"Error: 'python' or analyzer script not found ({analyzer_script_path}).")

if __name__ == "__main__":
    original_log_file = perform_logging_session() 

    if original_log_file and os.path.exists(original_log_file):
        duplicated_log_file = duplicate_csv(original_log_file)
        
        if duplicated_log_file:
            run_analyzer_on_csv(duplicated_log_file)
            print(f"Process complete. Original log: {original_log_file}, Analyzed log copy: {duplicated_log_file}")
    else:
        print("OBD logging did not produce a valid CSV file. Skipping analysis.") 