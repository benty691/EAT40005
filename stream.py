import requests, random, datetime, time

# API Handler
API_URL = "https://binkhoale1812-obd-logger.hf.space/ingest"
DRIVING_STYLES = ["aggressive", "passive", "normal"]
SESSION_TS = datetime.datetime.now().isoformat()

# Random data generation
def generate_fake_obd_data():
    return {
        "RPM": random.randint(800, 4000),
        "THROTTLE_POS": round(random.uniform(5, 80), 2),
        "SPEED": random.randint(0, 120),
        "FUEL_PRESSURE": random.randint(30, 70),
        "ENGINE_LOAD": round(random.uniform(10, 80), 2),
        "COOLANT_TEMP": random.randint(70, 110),
        "INTAKE_TEMP": random.randint(20, 60),
        "MAF": round(random.uniform(0.5, 10.0), 2)
    }

# Handshake with server
def send_control_signal(stage):
    requests.post(API_URL, json={
        "timestamp": SESSION_TS,
        "driving_style": "none",
        "data": {},
        "status": stage  # 'start' or 'end'
    })

# Simulate driver sensor logging
def simulate_logging():
    send_control_signal("start")
    total_duration = 15
    interval = 0.2
    num_entries = int(total_duration / interval)
    for i in range(num_entries):
        payload = {
            "timestamp": SESSION_TS,
            "driving_style": random.choice(DRIVING_STYLES),
            "data": generate_fake_obd_data()
        }
        res = requests.post(API_URL, json=payload)
        time.sleep(interval)
    input("Press [Q] to stop logging...")
    send_control_signal("end")

if __name__ == "__main__":
    simulate_logging()
