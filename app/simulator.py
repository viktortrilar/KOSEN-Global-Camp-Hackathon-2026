import asyncio, math, random, time, json
import paho.mqtt.client as mqtt
import os

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))

ROOMS = {
    "sendai_lab": {
        "base_temp":  22.0,
        "base_humid": 55.0,
        "base_co2":   450.0,
        "base_power": 800.0,
        "ac_on":      True,
        "occupied":   True,
    },
    "server_room": {
        "base_temp":  18.0,
        "base_humid": 40.0,
        "base_co2":   420.0,
        "base_power": 2400.0,
        "ac_on":      True,
        "occupied":   False,
    },
    "meeting_room1": {
        "base_temp":  23.0,
        "base_humid": 58.0,
        "base_co2":   520.0,
        "base_power": 500.0,
        "ac_on":      True,
        "occupied":   True,
    },
    "meeting_room2": {
        "base_temp":  25.0,
        "base_humid": 62.0,
        "base_co2":   580.0,
        "base_power": 150.0,
        "ac_on":      False,
        "occupied":   False,
    },
    "office": {
        "base_temp":  21.0,
        "base_humid": 52.0,
        "base_co2":   480.0,
        "base_power": 1200.0,
        "ac_on":      True,
        "occupied":   True,
    },
}

def noisy(value, noise=0.5):
    return round(value + random.gauss(0, noise), 2)

def door_state(room: str) -> str:
    """Cycles demo doors open periodically so the UI can show changing state."""
    cycles = {
        "sendai_lab": (60, 20),
        "meeting_room1": (90, 15),
        "meeting_room2": (120, 10),
        "office": (150, 12),
        "server_room": (180, 8),
    }
    period, open_seconds = cycles.get(room, (60, 20))
    return "open" if int(time.time()) % period < open_seconds else "closed"

def day_cycle(base, amplitude):
    hour = (time.time() % 86400) / 3600
    return base + amplitude * math.sin((hour - 6) * math.pi / 12)

async def simulate(client: mqtt.Client):
    while True:
        for room, cfg in ROOMS.items():
            sensors_payload = {
                "timestamp":   time.time(),
                "room":        room,
                "temperature": noisy(day_cycle(cfg["base_temp"],  2)),
                "humidity":    noisy(day_cycle(cfg["base_humid"], 5), 1),
                "co2":         noisy(day_cycle(cfg["base_co2"],  50), 5),
                "power":       noisy(cfg["base_power"], 20),
                "ac_on":       cfg["ac_on"],
                "occupied":    cfg["occupied"],
            }
            client.publish(f"room/{room}/sensors", json.dumps(sensors_payload))

            # Keep sendai_lab openings owned by the CV service so the live
            # person count and door state are not overwritten by the demo simulator.
            if room == "sendai_lab":
                continue

            openings_payload = {
                "timestamp":    time.time(),
                "room":         room,
                "source":       "simulator",
                "occupied":     cfg["occupied"],
                "person_count": 0,
                "openings":     {
                    "door":   door_state(room),
                    "window": "closed",
                },
            }
            client.publish(f"room/{room}/openings", json.dumps(openings_payload))

        await asyncio.sleep(5)


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    print(f"[SIM] Publishing to mqtt://{MQTT_HOST}:{MQTT_PORT} — Ctrl+C to stop")
    asyncio.run(simulate(client))
