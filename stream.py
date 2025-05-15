import requests
import time
import datetime
import random

API_URL = "https://binkhoale1812-obd-logger.hf.space/ingest"
DRIVING_STYLES = ["aggressive", "passive", "normal"]

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

def simulate_logging():
    total_duration = 15  # seconds
    interval = 0.2       # seconds per sample
    num_entries = int(total_duration / interval)

    for i in range(num_entries):
        payload = {
            "timestamp": datetime.datetime.now().isoformat(),
            "driving_style": random.choice(DRIVING_STYLES),
            "data": generate_fake_obd_data()
        }
        try:
            res = requests.post(API_URL, json=payload)
            if res.status_code == 200:
                print(f"[✓] Entry {i+1} sent: {payload['timestamp']}")
            else:
                print(f"[✗] Failed: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[!] Error sending data: {e}")
        time.sleep(interval)

    print("✅ Simulation complete. Now check cleaned CSV output.")

if __name__ == "__main__":
    simulate_logging()
