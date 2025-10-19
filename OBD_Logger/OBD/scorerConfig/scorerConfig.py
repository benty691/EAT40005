
weights:
  RPM: 0.25              # Engine speed (idle vs redline)
  THROTTLE_POS: 0.30     # Throttle position (most direct indicator)
  ENGINE_LOAD: 0.20      # How hard the engine is working
  MAF: 0.15              # Mass Air Flow (fuel consumption rate)
  SPEED: 0.05            # Vehicle speed (context-dependent)
  INTAKE_PRESSURE: 0.05  # Manifold pressure (turbo/boost indicator)

# Spike Detection Thresholds
spike_thresholds:
  moderate_spike: 65     # Score above which counts as "spike"
  extreme_spike: 85      # Score above which counts as "extreme"
  spike_percentage_threshold: 3   # % of drive that triggers penalty
  extreme_percentage_threshold: 1 # % of extreme spikes that triggers penalty

# Penalty Multipliers
penalty_multipliers:
  p95_multiplier: 0.3    # Penalty multiplier for 95th percentile
  p99_multiplier: 0.5    # Penalty multiplier for 99th percentile
  spike_freq_multiplier: 2.0    # Penalty per % over threshold
  extreme_freq_multiplier: 3.0  # Penalty per % over extreme threshold

# Aggregate Score Calculation
aggregate_weights:
  mean_weight: 0.7       # Weight given to mean score
  p75_weight: 0.3        # Weight given to 75th percentile

# Driving Style Categories (score ranges)
style_categories:
  very_calm: [0, 20]
  calm: [20, 40]
  moderate: [40, 55]
  aggressive: [55, 70]
  very_aggressive: [70, 100]

# Bounds File Settings
bounds:
  file: "obd_bounds.json"
  auto_update: true      # Automatically update bounds with new data
  
# Theoretical Maximum Values (used for initial normalization)
# These will be replaced as real data comes in
theoretical_maxes:
  RPM: 7000
  THROTTLE_POS: 100
  ENGINE_LOAD: 100
  MAF: 300
  SPEED: 250
  INTAKE_PRESSURE: 250

# Theoretical Minimum Values
theoretical_mins:
  RPM: 0
  THROTTLE_POS: 0
  ENGINE_LOAD: 0
  MAF: 0
  SPEED: 0
  INTAKE_PRESSURE: 0

# Output Settings
output:
  save_scored_csv: true
  visualization: true
  verbose: true