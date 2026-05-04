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
    "meeting_room_a": {
        "base_temp":  24.0,
        "base_humid": 60.0,
        "base_co2":   600.0,
        "base_power": 400.0,
        "ac_on":      False,
        "occupied":   False,
    }
}

def noisy(value, noise=0.5):
    return round(value + random.gauss(0, noise), 2)

def day_cycle(base, amplitude):
    hour = (time.time() % 86400) / 3600
    return base + amplitude * math.sin((hour - 6) * math.pi / 12)

async def simulate(client):
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

            openings_payload = {
                "timestamp": time.time(),
                "room":      room,
                "openings":  {
                    "door":   "closed",
                    "window": "closed",
                }
            }
            client.publish(f"room/{room}/openings", json.dumps(openings_payload))

        await asyncio.sleep(5)
