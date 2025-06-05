import pandas as pd
import numpy as np
import argparse
import os


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


KPH_TO_MPS = 1 / 3.6
G_ACCELERATION = 9.80665  
MIN_MOVING_SPEED_KPH = 2 # have to be moving

AGGRESSIVE_RPM_ENTRY_THRESHOLD = 2700
AGGRESSIVE_THROTTLE_ENTRY_THRESHOLD = 40  
AGGRESSIVE_RPM_HOLD_THRESHOLD = 2300
HARSH_BRAKING_THRESHOLD_G = -0.25

# roc
AGGRESSIVE_RPM_ROC_THRESHOLD = 500  
AGGRESSIVE_THROTTLE_ROC_THRESHOLD = 45 
POSITIVE_ACCEL_FOR_ROC_CHECK_G = 0.1 

MODERATE_RPM_THRESHOLD = 2100
MODERATE_THROTTLE_THRESHOLD = 25 

MIN_DATA_POINTS_FOR_ROC = 2 

def load_and_preprocess_data(csv_filepath):
    """Loads OBD data from CSV and preprocesses it."""
    if not os.path.exists(csv_filepath):
        print(f"Error: File not found at {csv_filepath}")
        return None

    try:
        df = pd.read_csv(csv_filepath)
    except Exception as e:
        print(f"Error loading CSV {csv_filepath}: {e}")
        return None

    print(f"Successfully loaded {csv_filepath} with {len(df)} rows.")

    if 'timestamp' not in df.columns:
        print("Error: 'timestamp' column is missing from the CSV.")
        return None
        
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values(by='timestamp').reset_index(drop=True)

    df['delta_time_s'] = df['timestamp'].diff().dt.total_seconds()
    if not df.empty:
        df.loc[0, 'delta_time_s'] = 0
    else:
        # Handle empty DataFrame after potential filtering or if it was empty to begin with
        return df # Or handle error appropriately

    numeric_cols = ['SPEED', 'RPM', 'THROTTLE_POS']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            print(f"Warning: Column {col} not found. It will be filled with NaN.")
            df[col] = np.nan
            
    df[numeric_cols] = df[numeric_cols].fillna(method='ffill').fillna(0)

    if 'SPEED' in df.columns:
        df['SPEED_mps'] = df['SPEED'] * KPH_TO_MPS
    else:
        df['SPEED_mps'] = 0

    if len(df) >= MIN_DATA_POINTS_FOR_ROC:
        df['acceleration_mps2'] = df['SPEED_mps'].diff() / df['delta_time_s']
        df['acceleration_mps2'] = df['acceleration_mps2'].replace([np.inf, -np.inf], 0).fillna(0)
        if not df.empty: df.loc[0, 'acceleration_mps2'] = 0
        df['acceleration_g'] = df['acceleration_mps2'] / G_ACCELERATION
        if not df.empty: df.loc[0, 'acceleration_g'] = 0
        df['acceleration_g'] = df['acceleration_g'].fillna(0)

        if 'RPM' in df.columns:
            df['RPM_roc'] = df['RPM'].diff() / df['delta_time_s']
            df['RPM_roc'] = df['RPM_roc'].replace([np.inf, -np.inf], 0).fillna(0)
            if not df.empty: df.loc[0, 'RPM_roc'] = 0
        else:
            df['RPM_roc'] = 0

        if 'THROTTLE_POS' in df.columns:
            df['THROTTLE_roc'] = df['THROTTLE_POS'].diff() / df['delta_time_s']
            df['THROTTLE_roc'] = df['THROTTLE_roc'].replace([np.inf, -np.inf], 0).fillna(0)
            if not df.empty: df.loc[0, 'THROTTLE_roc'] = 0
        else:
            df['THROTTLE_roc'] = 0
    else:
        # Not enough data for RoC calculations, fill with 0 or handle as error
        df['acceleration_mps2'] = 0
        df['acceleration_g'] = 0
        df['RPM_roc'] = 0
        df['THROTTLE_roc'] = 0
        print("Warning: Not enough data points for full RoC calculations. Output might be limited.")

    print("Preprocessing complete.")
    return df

def classify_driving_style_stateful(df):
    if df.empty or not all(col in df.columns for col in ['RPM', 'THROTTLE_POS', 'SPEED', 'acceleration_g']):
        print("Warning: Missing one or more required columns for stateful classification (RPM, THROTTLE_POS, SPEED, acceleration_g).")
        return pd.Series([DRIVING_STYLE_UNKNOWN] * len(df), index=df.index, dtype=str)

    driving_styles = [DRIVING_STYLE_UNKNOWN] * len(df)
    current_style = DRIVING_STYLE_PASSIVE

    for i in range(len(df)):
        rpm = df.loc[i, 'RPM']
        throttle = df.loc[i, 'THROTTLE_POS']
        speed_kph = df.loc[i, 'SPEED']
        accel_g = df.loc[i, 'acceleration_g']
        rpm_roc = df.loc[i, 'RPM_roc']
        throttle_roc = df.loc[i, 'THROTTLE_roc']

        row_style = DRIVING_STYLE_PASSIVE
        is_moving = speed_kph > MIN_MOVING_SPEED_KPH

        is_hard_braking_trigger = accel_g < HARSH_BRAKING_THRESHOLD_G and is_moving
        
        is_high_abs_rpm_throttle_trigger = (rpm > AGGRESSIVE_RPM_ENTRY_THRESHOLD and
                                            throttle > AGGRESSIVE_THROTTLE_ENTRY_THRESHOLD and
                                            is_moving)
        
        is_actively_accelerating = accel_g > POSITIVE_ACCEL_FOR_ROC_CHECK_G
        
        is_high_roc_trigger = (is_moving and
                               is_actively_accelerating and
                               (rpm_roc > AGGRESSIVE_RPM_ROC_THRESHOLD or 
                                throttle_roc > AGGRESSIVE_THROTTLE_ROC_THRESHOLD))

        is_currently_aggressive_event = is_hard_braking_trigger or is_high_abs_rpm_throttle_trigger or is_high_roc_trigger

        if current_style == DRIVING_STYLE_AGGRESSIVE:
            if is_currently_aggressive_event:
                row_style = DRIVING_STYLE_AGGRESSIVE
            elif rpm > AGGRESSIVE_RPM_HOLD_THRESHOLD and is_moving:
                row_style = DRIVING_STYLE_AGGRESSIVE
            else:
                if (rpm > MODERATE_RPM_THRESHOLD or throttle > MODERATE_THROTTLE_THRESHOLD) and is_moving:
                    row_style = DRIVING_STYLE_MODERATE
                else:
                    row_style = DRIVING_STYLE_PASSIVE
        else:
            if is_currently_aggressive_event:
                row_style = DRIVING_STYLE_AGGRESSIVE
            else:
                if (rpm > MODERATE_RPM_THRESHOLD or throttle > MODERATE_THROTTLE_THRESHOLD) and is_moving:
                    row_style = DRIVING_STYLE_MODERATE
                else:
                    row_style = DRIVING_STYLE_PASSIVE
        
        driving_styles[i] = row_style
        current_style = row_style

    print("Stateful driving style classification complete.")
    return pd.Series(driving_styles, index=df.index)

def main():
    parser = argparse.ArgumentParser(description="Analyze OBD CSV log data for driving behavior (stateful).")
    parser.add_argument("csv_filepath", help="Path to the OBD log CSV file.")
    parser.add_argument("--output_csv", help="Path to save the analyzed data CSV file.", default=None)
    args = parser.parse_args()

    df = load_and_preprocess_data(args.csv_filepath)

    if df is None or df.empty:
        print("No data to process after loading or preprocessing.")
        return

    df['driving_style_analyzed'] = classify_driving_style_stateful(df)

    print("\n--- Analysis Summary ---")
    print("Driving Style Distribution (Analyzed):")
    counts = df['driving_style_analyzed'].value_counts(dropna=False)
    percentages = df['driving_style_analyzed'].value_counts(normalize=True, dropna=False) * 100
    summary_df = pd.DataFrame({'Count': counts, 'Percentage': percentages})
    print(summary_df)

    if args.output_csv:
        try:
            output_path = args.output_csv
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            df.to_csv(output_path, index=False)
            print(f"\nAnalyzed data saved to {output_path}")
        except Exception as e:
            print(f"Error saving output CSV to {args.output_csv}: {e}")
    else:
        print("\n--- First 20 Rows of Analyzed Data (showing key fields) ---")
        display_cols = ['timestamp', 'SPEED', 'RPM', 'THROTTLE_POS', 'acceleration_g', 'driving_style_analyzed']
        display_cols = [col for col in display_cols if col in df.columns]
        if display_cols: print(df[display_cols].head(20))
        else: print("Key display columns not found in DataFrame.")

if __name__ == "__main__":
    main() 