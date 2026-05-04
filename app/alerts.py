from database import insert_alert

COST_PER_WH = 28.93 / 1000  # ¥28.93/kWh → ¥0.02893/Wh (Japan commercial rate)

async def evaluate(room: str, sensors: dict, openings: dict):
    alerts = []

    temp     = sensors.get("temperature", 0)
    power    = sensors.get("power", 0)
    co2      = sensors.get("co2", 0)
    humid    = sensors.get("humidity", 0)
    ac_on    = sensors.get("ac_on", False)
    occupied = sensors.get("occupied", False)

    cost_per_hour = round(power * COST_PER_WH, 2)

    # Heat leak: opening + AC on
    for name, state in openings.items():
        if state == "open" and ac_on:
            msg = f"{name.capitalize()} is OPEN while AC is running — ¥{cost_per_hour}/hr wasted"
            alerts.append({"type": "heat_leak", "severity": "high", "message": msg})

    # Unoccupied but AC running
    if not occupied and ac_on and power > 200:
        msg = f"Room empty but AC running — ¥{cost_per_hour}/hr wasted"
        alerts.append({"type": "empty_room", "severity": "medium", "message": msg})

    # CO2 levels
    if co2 > 1500:
        msg = f"CO₂ critically high at {co2}ppm — immediate ventilation needed"
        alerts.append({"type": "co2_critical", "severity": "high", "message": msg})
    elif co2 > 1000:
        msg = f"CO₂ at {co2}ppm — ventilation recommended"
        alerts.append({"type": "co2_high", "severity": "medium", "message": msg})

    # Power spike
    if power > 1500:
        msg = f"Power spike detected: {power}W (¥{cost_per_hour}/hr)"
        alerts.append({"type": "power_spike", "severity": "high", "message": msg})

    # Overcooling
    if temp < 18 and ac_on:
        msg = f"Room overcooled at {temp}°C — raise setpoint to save energy"
        alerts.append({"type": "overcooling", "severity": "low", "message": msg})

    # Humidity
    if humid > 70:
        msg = f"Humidity high at {humid}% — condensation risk"
        alerts.append({"type": "humidity_high", "severity": "medium", "message": msg})

    for a in alerts:
        await insert_alert(room, a["type"], a["severity"], a["message"])

    return alerts
