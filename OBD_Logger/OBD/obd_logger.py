import obd
import time
import datetime
import csv
import os
from collections import deque 
import numpy as np 
import shutil
import subprocess
import sys # For non-blocking input
import select # For non-blocking input (Unix-like)


# Critical PIDs for fuel consumption calculations - highest frequency
CRITICAL_FUEL_PIDS = [
    obd.commands.RPM,           
    obd.commands.SPEED,           
    obd.commands.THROTTLE_POS,  
    obd.commands.MAF,    
]       

# Secondary PIDs for efficiency context - medium frequency
SECONDARY_FUEL_PIDS = [
    obd.commands.ENGINE_LOAD,      
    obd.commands.INTAKE_PRESSURE,  
]

# Tertiary PIDs for fuel trim analysis - low frequency
TERTIARY_FUEL_PIDS = [
    obd.commands.SHORT_FUEL_TRIM_1,  
    obd.commands.SHORT_FUEL_TRIM_2,   
    obd.commands.LONG_FUEL_TRIM_1,   
    obd.commands.LONG_FUEL_TRIM_2,  
]

HIGH_FREQUENCY_PIDS = CRITICAL_FUEL_PIDS
LOW_FREQUENCY_PIDS_POOL = SECONDARY_FUEL_PIDS + TERTIARY_FUEL_PIDS

ALL_PIDS_TO_LOG = HIGH_FREQUENCY_PIDS + LOW_FREQUENCY_PIDS_POOL

CSV_FILENAME_BASE = "obd_data_log" 
# Define new structured log directories relative to the OBD_Logger/OBD directory
LOGS_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs") # Corrected: Up two levels to Base, then into logs
FUEL_LOGS_DIR = os.path.join(LOGS_BASE_DIR, "FuelLogs")
ANALYSED_LOGS_DIR = os.path.join(LOGS_BASE_DIR, "analysedLogsAutomated")
# Keep legacy directories for backward compatibility if needed
ORIGINAL_CSV_DIR = FUEL_LOGS_DIR  # Point to new fuel logs directory
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

    
def perform_logging_session(connection):
    """Perform a single logging session with an existing OBD connection."""
    print(f"\n🚗 Starting new fuel efficiency logging session")
    print("Commands:")
    print("  - Type 'next' and press Enter to finish this drive and start a new one")
    print("  - Type 'quit' and press Enter to stop all logging")

    
    # Optimized sampling intervals for fuel efficiency monitoring
    CRITICAL_PID_INTERVAL = 0.65        # Critical PIDs every 0.25s (4Hz) - RPM, SPEED, THROTTLE_POS, MAF
    SECONDARY_PID_INTERVAL = 2.0        # Secondary PIDs every 2s - ENGINE_LOAD, INTAKE_PRESSURE  
    TERTIARY_PID_INTERVAL = 5.0        # Tertiary PIDs every 15s - Fuel trims
    
    # Timing trackers for different PID groups
    last_critical_poll_time = time.monotonic() - CRITICAL_PID_INTERVAL  # Start immediately
    last_secondary_poll_time = time.monotonic() - SECONDARY_PID_INTERVAL  # Start immediately
    last_tertiary_poll_time = time.monotonic() - TERTIARY_PID_INTERVAL   # Start immediately
    
    # Legacy compatibility - use critical interval as base
    BASE_LOG_INTERVAL = CRITICAL_PID_INTERVAL
    
    current_pid_values = {pid.name: '' for pid in ALL_PIDS_TO_LOG} 

    # Create log directories - include the new analysed logs directory
    for dir_path in [FUEL_LOGS_DIR, ANALYSED_LOGS_DIR, DUPLICATE_CSV_DIR]:
        try:
            os.makedirs(dir_path, exist_ok=True)
            print(f"Ensured directory exists: {dir_path}")
        except OSError as e:
            print(f"Error creating directory {dir_path}: {e}. Attempting to use current directory.")
            # Fallback logic may be needed if creation fails critically
            if dir_path == FUEL_LOGS_DIR: # Critical for saving fuel log
                 print("Cannot create fuel log directory. Exiting.")
                 return None 

    current_session_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file_name_only = f"{CSV_FILENAME_BASE}_{current_session_timestamp}.csv"
    original_csv_filepath = os.path.join(ORIGINAL_CSV_DIR, csv_file_name_only)

    try:
        if not connection or not connection.is_connected():
            print("OBD connection not available")
            return None, "quit"
            
        print(f"Using existing OBD connection: {connection.port_name()}")

        # Creating initial full PID sample to have fully populated rows from beginning 
        print("\nPerforming initial full PID sample...")
        initial_log_entry = {
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        print("Polling initial Critical Fuel PIDs...")
        for pid_command in CRITICAL_FUEL_PIDS:
            value = get_pid_value(connection, pid_command)
            current_pid_values[pid_command.name] = value if value is not None else ''
            initial_log_entry[pid_command.name] = current_pid_values[pid_command.name]

        print("Polling initial Secondary Fuel PIDs...")
        for pid_command in SECONDARY_FUEL_PIDS:
            value = get_pid_value(connection, pid_command)
            current_pid_values[pid_command.name] = value if value is not None else ''
            initial_log_entry[pid_command.name] = current_pid_values[pid_command.name]
            
        print("Polling initial Tertiary Fuel PIDs...")
        for pid_command in TERTIARY_FUEL_PIDS:
            value = get_pid_value(connection, pid_command)
            current_pid_values[pid_command.name] = value if value is not None else ''
            initial_log_entry[pid_command.name] = current_pid_values[pid_command.name]

        for pid_obj in ALL_PIDS_TO_LOG:
            if pid_obj.name not in initial_log_entry:
                initial_log_entry[pid_obj.name] = '' # Default to empty if somehow missed

        # Empty driving style and fuel columns
        initial_log_entry['driving_style'] = ''
        initial_log_entry['Fuel consumed'] = ''
        initial_log_entry['Fuel Efficiency (L/100KM)'] = ''
        initial_log_entry['Route'] = ''
        initial_log_entry['Distance'] = ''

    except Exception as e:
        print(f"An error occurred during connection or initial PID sample: {e}")
        if connection and connection.is_connected():
            connection.close()
        return None

    file_exists = os.path.isfile(original_csv_filepath)
    try:
        with open(original_csv_filepath, 'a', newline='') as csvfile:
            # Headers for fuel efficiency logging plus placeholder for driving style and fuel data
            header_names = ['timestamp'] + [pid.name for pid in ALL_PIDS_TO_LOG] + ['driving_style', 'Fuel consumed', 'Fuel Efficiency (L/100KM)']

            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(original_csv_filepath) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {original_csv_filepath} with headers: {header_names}")

            if initial_log_entry: 
                writer.writerow(initial_log_entry)
                csvfile.flush()
                print(f"Logged initial full sample with all fuel efficiency PIDs.")
            
            log_count = 0
            user_stop_requested = False

            print(f"\nOptimized fuel efficiency logging started:")
            print(f"- Critical PIDs (RPM, SPEED, THROTTLE_POS, MAF) every {CRITICAL_PID_INTERVAL}s")
            print(f"- Secondary PIDs (ENGINE_LOAD, INTAKE_PRESSURE) every {SECONDARY_PID_INTERVAL}s") 
            print(f"- Tertiary PIDs (Fuel Trims) every {TERTIARY_PID_INTERVAL}s")
            
            while not user_stop_requested:
                # Check for non-blocking input
                if select.select([sys.stdin], [], [], 0.0)[0]:
                    user_command = sys.stdin.readline().strip().lower()
                    if user_command == "next":
                        print("\nUser typed 'next'. Finishing current drive...")
                        user_stop_requested = True
                        break # Exit current session loop
                    elif user_command == "quit":
                        print("\nUser typed 'quit'. Stopping all logging...")
                        user_stop_requested = True
                        return original_csv_filepath, "quit"  # Signal to quit all sessions
                    else:
                        # Optional: Acknowledge other input if needed, or just ignore
                        print(f"Input detected: '{user_command}'. Type 'next' or 'quit'.", end='\r') 

                loop_start_time = time.monotonic()
                current_datetime = datetime.datetime.now()
                timestamp_iso = current_datetime.isoformat()
                
                critical_reads = 0
                secondary_reads = 0
                tertiary_reads = 0
                
                # Always poll critical PIDs (highest frequency)
                if (time.monotonic() - last_critical_poll_time) >= CRITICAL_PID_INTERVAL:
                    for pid_command in CRITICAL_FUEL_PIDS:
                        value = get_pid_value(connection, pid_command)
                        current_pid_values[pid_command.name] = value if value is not None else ''
                        if value is not None:
                            critical_reads += 1
                    last_critical_poll_time = time.monotonic()
                
                # Poll secondary PIDs at medium frequency
                if (time.monotonic() - last_secondary_poll_time) >= SECONDARY_PID_INTERVAL:
                    for pid_command in SECONDARY_FUEL_PIDS:
                        value = get_pid_value(connection, pid_command)
                        current_pid_values[pid_command.name] = value if value is not None else ''
                        if value is not None:
                            secondary_reads += 1
                    last_secondary_poll_time = time.monotonic()
                
                # Poll tertiary PIDs at low frequency
                if (time.monotonic() - last_tertiary_poll_time) >= TERTIARY_PID_INTERVAL:
                    for pid_command in TERTIARY_FUEL_PIDS:
                        value = get_pid_value(connection, pid_command)
                        current_pid_values[pid_command.name] = value if value is not None else ''
                        if value is not None:
                            tertiary_reads += 1
                    last_tertiary_poll_time = time.monotonic()


                final_log_entry = {
                    'timestamp': timestamp_iso
                }
                # Add all PID values for this cycle from current_pid_values
                for pid_obj in ALL_PIDS_TO_LOG:
                     final_log_entry[pid_obj.name] = current_pid_values.get(pid_obj.name, '')

                final_log_entry['driving_style'] = ''
                final_log_entry['Fuel consumed'] = ''
                final_log_entry['Fuel Efficiency (L/100KM)'] = ''
                final_log_entry['Route'] = ''
                final_log_entry['Distance'] = ''

                writer.writerow(final_log_entry)
                csvfile.flush()  

                log_count += 1
                if log_count % 10 == 0: 
                    status_msg = f"Entry {log_count} - Critical: {critical_reads}/{len(CRITICAL_FUEL_PIDS)}"
                    if secondary_reads > 0:
                        status_msg += f" Secondary: {secondary_reads}/{len(SECONDARY_FUEL_PIDS)}"
                    if tertiary_reads > 0:
                        status_msg += f" Tertiary: {tertiary_reads}/{len(TERTIARY_FUEL_PIDS)}"
                    print(status_msg + " " * 20, end='\r') # Padding to clear previous line
                
                elapsed_time_in_loop = time.monotonic() - loop_start_time
                sleep_duration = max(0, BASE_LOG_INTERVAL - elapsed_time_in_loop)
                time.sleep(sleep_duration)

    except KeyboardInterrupt:
        print("\nStopping data logging due to user interruption (Ctrl+C).")
    except Exception as e:
        print(f"An error occurred during logging: {e}")
    finally:
        # Clear the status line before printing final messages
        print(" " * 100, end='\r') 
        print(f"Drive completed - data saved to: {os.path.basename(original_csv_filepath)}")

    return original_csv_filepath, "next"  # Default to "next" for continuing

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

def run_analyzer_on_csv(original_csv_path):
    """Run analyzer on the original fuel log and save to analysedLogsAutomated directory."""
    if not original_csv_path or not os.path.exists(original_csv_path):
        print(f"Error: Original CSV not found for analysis: {original_csv_path}")
        return None

    # Analyzer script is in the same directory as this logger script
    analyzer_script_path = os.path.join(os.path.dirname(__file__), "obd_analyzer.py") 
    
    if not os.path.exists(analyzer_script_path):
        print(f"CRITICAL Error: Analyzer script not found at {analyzer_script_path}")
        return None

    # Create analyzed filename with _analyzed suffix
    original_filename = os.path.basename(original_csv_path)
    base, ext = os.path.splitext(original_filename)
    analyzed_filename = f"{base}_analyzed{ext}"
    analyzed_output_path = os.path.join(ANALYSED_LOGS_DIR, analyzed_filename)

    command = [
        "python3",
        analyzer_script_path,
        original_csv_path,
        "--output_csv",
        analyzed_output_path   
    ]
    
    print(f"🔍 Running analyzer: {' '.join(command)}")
    try:
        process = subprocess.run(command, check=True, capture_output=True, text=True, cwd=os.path.dirname(__file__))
        print("Analyzer Output:\n", process.stdout)
        if process.stderr: 
            print("Analyzer Errors:\n", process.stderr)
        print(f"✅ Analysis complete. Results saved to: {os.path.basename(analyzed_output_path)}")
        return analyzed_output_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running analyzer: {e}\nStdout: {e.stdout}\nStderr: {e.stderr}")
        return None
    except FileNotFoundError:
        print(f"❌ Error: 'python3' or analyzer script not found ({analyzer_script_path}).")
        return None

def initialize_obd_connection():
    """Initialize OBD connection once for multiple sessions."""
    connection = None
    
    try:
        if USE_WIFI_SETTINGS:
            print(f"Attempting to connect to WiFi adapter at {WIFI_ADAPTER_HOST}:{WIFI_ADAPTER_PORT} using protocol {WIFI_PROTOCOL}...")
            connection = obd.OBD(protocol=WIFI_PROTOCOL, 
                                 host=WIFI_ADAPTER_HOST, 
                                 port=WIFI_ADAPTER_PORT, 
                                 fast=False,
                                 timeout=30) 
        else:
            print("Attempting to connect via socat PTY /dev/ttys006...")
            connection = obd.OBD("/dev/ttys006", fast=True, timeout=30)

        if not connection.is_connected():
            print("Failed to connect to OBD-II adapter.")
            print(f"Connection status: {connection.status()}")
            return None
        
        print(f"Successfully connected to OBD-II adapter: {connection.port_name()}")
        print(f"Adapter status: {connection.status()}")
        return connection
        
    except Exception as e:
        print(f"An error occurred during OBD connection: {e}")
        return None

def main():
    """Main function to handle multiple logging sessions."""
    print("🚗 Fuel Efficiency OBD Logger - Multi-Session Mode")
    print("=" * 50)
    
    # Initialize OBD connection once
    connection = initialize_obd_connection()
    if not connection:
        print("❌ Could not establish OBD connection. Exiting.")
        return
    
    session_count = 0
    logged_files = []
    
    try:
        while True:
            session_count += 1
            print(f"\n📊 Session {session_count} ready to start")
            
            # Perform logging session
            result = perform_logging_session(connection)
            
            if isinstance(result, tuple):
                csv_file, command = result
            else:
                csv_file, command = result, "quit"  # Fallback
            
            # Handle the result
            if csv_file and os.path.exists(csv_file):
                logged_files.append(csv_file)
                print(f"✅ Drive {session_count} saved: {os.path.basename(csv_file)}")
                
                # Automatically run analyzer on the completed drive
                print(f"\n🔍 Starting automated analysis for drive {session_count}...")
                analyzed_file = run_analyzer_on_csv(csv_file)
                if analyzed_file:
                    print(f"📊 Analysis complete for drive {session_count}")
                else:
                    print(f"⚠️ Analysis failed for drive {session_count}, but drive data is still saved")
            
            # Check if user wants to quit
            if command == "quit":
                print("\n🏁 Stopping all logging as requested")
                break
            
            # Otherwise continue to next session
            print(f"\n🔄 Ready for next drive (Session {session_count + 1})")
    
    except KeyboardInterrupt:
        print("\n⏹️  Logging stopped by user (Ctrl+C)")
    
    finally:
        # Close OBD connection
        if connection and connection.is_connected():
            print("Closing OBD-II connection...")
            connection.close()
        
        # Print summary
        print("\n" + "=" * 50)
        print(f"📈 LOGGING SUMMARY")
        print(f"Total drives logged: {len(logged_files)}")
        if logged_files:
            print("Raw fuel logs saved to: logs/FuelLogs/")
            print("Analyzed logs saved to: logs/analysedLogsAutomated/")
            print("\nFiles created:")
            for file in logged_files:
                print(f"  - {os.path.basename(file)}")
            print(f"\n📤 Run bulk upload when WiFi is available to send data to MongoDB")
        print("=" * 50)

if __name__ == "__main__":
    main() 