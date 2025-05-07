import obd
import time
import datetime
import csv
import os

# --- Configuration ---
LOG_INTERVAL_SECONDS = .2  # How often to log data (in seconds)
# Common PIDs to start with. Add or remove as needed.
# You can find more PIDs in the obd.commands documentation or by querying supported commands.
PIDS_TO_MONITOR = [
    # Engine Parameters
    obd.commands.RPM,
    obd.commands.ENGINE_LOAD,
    obd.commands.ABSOLUTE_LOAD,
    obd.commands.COOLANT_TEMP,
    obd.commands.INTAKE_TEMP,
    obd.commands.AMBIANT_AIR_TEMP, # Note: 'AMBIENT_AIR_TEMP' is the correct spelling in python-obd
    obd.commands.OIL_TEMP,
    obd.commands.TIMING_ADVANCE,
    obd.commands.MAF,
    obd.commands.INTAKE_PRESSURE, # MAP Sensor
    obd.commands.BAROMETRIC_PRESSURE,
    obd.commands.RUN_TIME,
    obd.commands.CONTROL_MODULE_VOLTAGE,

    # Throttle & Accelerator
    obd.commands.THROTTLE_POS,
    obd.commands.RELATIVE_THROTTLE_POS,
    obd.commands.THROTTLE_POS_B, # If multiple throttle bodies
    #obd.commands.ACCEL_POS_D,
    #obd.commands.ACCEL_POS_E,
    #obd.commands.COMMANDED_THROTTLE_ACTUATOR,
    obd.commands.RELATIVE_ACCEL_POS,

    # Fuel System
    obd.commands.FUEL_LEVEL,
    obd.commands.FUEL_STATUS,
    obd.commands.FUEL_PRESSURE,
    obd.commands.FUEL_RAIL_PRESSURE_VAC,
    obd.commands.FUEL_RAIL_PRESSURE_DIRECT,
    obd.commands.FUEL_RAIL_PRESSURE_ABS,
    obd.commands.SHORT_FUEL_TRIM_1,
    obd.commands.LONG_FUEL_TRIM_1,
    obd.commands.SHORT_FUEL_TRIM_2, # For V-engines or dual bank
    obd.commands.LONG_FUEL_TRIM_2,  # For V-engines or dual bank
    obd.commands.COMMANDED_EQUIV_RATIO, # Lambda
    #obd.commands.ENGINE_FUEL_RATE,
    obd.commands.FUEL_TYPE,
    obd.commands.ETHANOL_PERCENT,
    #obd.commands.FUEL_INJECTION_TIMING,

    # Oxygen Sensors
    obd.commands.O2_SENSORS, # Bitmap of present O2 sensors
    obd.commands.O2_B1S1, # Bank 1, Sensor 1: Voltage, Short Term Fuel Trim
    obd.commands.O2_B1S2, # Bank 1, Sensor 2: Voltage
    obd.commands.O2_B2S1, # Bank 2, Sensor 1 (if applicable)
    obd.commands.O2_B2S2, # Bank 2, Sensor 2 (if applicable)
    # Add more O2 sensors if your vehicle has them (e.g., O2_B1S3, O2_B1S4, etc.)
    # Wideband O2 Sensors (if supported)
    obd.commands.O2_S1_WR_VOLTAGE, # Example, check specific command names for your needs
    obd.commands.O2_S1_WR_CURRENT,

    # Emissions Systems
    obd.commands.COMMANDED_EGR,
    obd.commands.EGR_ERROR,
    #obd.commands.COMMANDED_EVAPORATIVE_PURGE,
    obd.commands.EVAP_VAPOR_PRESSURE,
    #obd.commands.ABSOLUTE_EVAP_VAPOR_PRESSURE,
    obd.commands.CATALYST_TEMP_B1S1,
    obd.commands.CATALYST_TEMP_B1S2,
    # obd.commands.PIDS_A, # 01-20 Supported PIDs
    # obd.commands.PIDS_B, # 21-40 Supported PIDs
    # obd.commands.PIDS_C, # 41-60 Supported PIDs
    
    # Vehicle Status & DTCs (Diagnostic Trouble Codes) - some might be better queried once per session
    obd.commands.STATUS, # Includes MIL status and DTC count
    # obd.commands.FREEZE_DTC, # DTC that caused freeze frame
    # obd.commands.GET_DTC, # To get confirmed, pending, permanent DTCs (use specific functions like get_dtc())
    obd.commands.DISTANCE_W_MIL,
    #obd.commands.TIME_W_MIL,
    obd.commands.DISTANCE_SINCE_DTC_CLEAR,
    obd.commands.TIME_SINCE_DTC_CLEARED,
    obd.commands.WARMUPS_SINCE_DTC_CLEAR,
    obd.commands.OBD_COMPLIANCE,

    # Other
    obd.commands.SPEED,           # Vehicle Speed (already present but good to keep)
    # obd.commands.VIN, # Vehicle Identification Number - usually queried once, not continuously
    obd.commands.HYBRID_BATTERY_REMAINING, # If hybrid
]
CSV_FILENAME_BASE = "obd_data_log" # Base name for the log file
LOG_SUBDIRECTORY = "logs" # Subdirectory to store log files

# --- Connection Settings (IMPORTANT: CONFIGURE FOR YOUR WIFI ADAPTER) ---
# If your WiFi OBD-II adapter has a static IP and port (most do):
WIFI_ADAPTER_HOST = "192.168.0.10"  # Replace with your OBD-II WiFi adapter's IP address
WIFI_ADAPTER_PORT = 35000           # Replace with your OBD-II WiFi adapter's port (often 35000)
# Protocol "6" is common for CAN bus vehicles. You might need to experiment if this fails.
WIFI_PROTOCOL = "6" 
USE_WIFI_SETTINGS = False # Set to False if you have a USB/Bluetooth adapter that auto-detects

# --- Helper Function to Get PID Value ---
def get_pid_value(connection, pid_command):
    """Queries a PID and returns its value, or None if not available or error."""
    try:
        response = connection.query(pid_command, force=True) # force=True can sometimes help with stubborn adapters
        if response.is_null() or response.value is None:
            return None
        # The obd library uses the Pint library for units.
        # We'll extract the magnitude (the numerical value).
        if hasattr(response.value, 'magnitude'):
            return response.value.magnitude
        return response.value
    except Exception as e:
        # print(f"Error querying {pid_command.name}: {e}") # Uncomment for verbose error details
        return None

# --- Main Logging Logic ---
def main():
    connection = None
    print("Starting OBD-II Data Logger...")

    # Define the logs directory path
    log_dir_path = os.path.join(os.getcwd(), LOG_SUBDIRECTORY)

    # Create the logs directory if it doesn't exist
    try:
        os.makedirs(log_dir_path, exist_ok=True)
        print(f"Log files will be saved in: {log_dir_path}")
    except OSError as e:
        print(f"Error creating directory {log_dir_path}: {e}")
        print("Log files will be saved in the current working directory instead.")
        log_dir_path = os.getcwd() # Fallback to current directory

    # Generate a unique filename for this session using a timestamp
    current_session_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file_name_only = f"{CSV_FILENAME_BASE}_{current_session_timestamp}.csv"
    CSV_FILENAME = os.path.join(log_dir_path, csv_file_name_only)

    # Attempt to connect
    try:
        if USE_WIFI_SETTINGS:
            print(f"Attempting to connect to WiFi adapter at {WIFI_ADAPTER_HOST}:{WIFI_ADAPTER_PORT} using protocol {WIFI_PROTOCOL}...")
            # For WiFi, ensure 'fast=False' for potentially better stability initially
            connection = obd.OBD(protocol=WIFI_PROTOCOL, 
                                 host=WIFI_ADAPTER_HOST, 
                                 port=WIFI_ADAPTER_PORT, 
                                 fast=False,
                                 timeout=30) # Increased timeout for WiFi
        else:
            print("Attempting to connect via socat PTY /dev/ttys010...")
            # Ensure this path matches the PTY from socat output (e.g., /dev/ttys010)
            connection = obd.OBD("/dev/ttys010", fast=False, timeout=30) # Auto-scan for USB/Bluetooth

        # Check connection status
        if not connection.is_connected():
            print("Failed to connect to OBD-II adapter.")
            print(f"Connection status: {connection.status()}")
            print("Please check:")
            print("1. The OBD-II adapter is plugged into the car and powered on.")
            print("2. The car's ignition is ON (or engine running).")
            print("3. If using WiFi, ensure your computer is connected to the OBD-II adapter's WiFi network.")
            print("4. If using WiFi, verify WIFI_ADAPTER_HOST, WIFI_ADAPTER_PORT, and WIFI_PROTOCOL in the script.")
            print("5. If using Bluetooth, ensure it's paired and available.")
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
            print("  No supported commands reported by the adapter. This might indicate a problem.")


    except Exception as e:
        print(f"An error occurred during connection: {e}")
        print("Ensure the python 'obd' library is installed ('pip install obd') and check adapter settings.")
        return

    # Prepare CSV file
    file_exists = os.path.isfile(CSV_FILENAME)
    try:
        with open(CSV_FILENAME, 'a', newline='') as csvfile:
            # Dynamically create header names from the PIDS_TO_MONITOR
            header_names = ['timestamp'] + [pid.name for pid in PIDS_TO_MONITOR]
            writer = csv.DictWriter(csvfile, fieldnames=header_names)

            if not file_exists or os.path.getsize(CSV_FILENAME) == 0:
                writer.writeheader()
                print(f"Created new CSV file: {CSV_FILENAME} with headers: {header_names}")
            else:
                print(f"Appending to existing CSV file: {CSV_FILENAME}")

            print(f"\nLogging data every {LOG_INTERVAL_SECONDS} second(s). Press Ctrl+C to stop.")
            
            log_count = 0
            while True:
                current_datetime = datetime.datetime.now()
                timestamp_iso = current_datetime.isoformat()
                
                log_entry = {'timestamp': timestamp_iso}
                successful_reads = 0

                for pid_command in PIDS_TO_MONITOR:
                    # Check if command is supported before querying (optional, but good practice)
                    # if pid_command in supported_commands: # This check can be slow if done every loop.
                    # Consider checking once at the start if performance is an issue.
                    value = get_pid_value(connection, pid_command)
                    log_entry[pid_command.name] = value if value is not None else '' # Store empty string for None
                    if value is not None:
                        successful_reads += 1
                    else:
                        print(f"Warning: Could not read {pid_command.name}")


                writer.writerow(log_entry)
                csvfile.flush()  # Ensure data is written to disk immediately

                log_count += 1
                if log_count % 10 == 0: # Print a status update every 10 logs
                    print(f"Logged entry {log_count}: {timestamp_iso} - Read {successful_reads}/{len(PIDS_TO_MONITOR)} PIDs successfully.")
                
                time.sleep(LOG_INTERVAL_SECONDS)

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