import paho.mqtt.client as mqtt

# Configuration - Remplace par l'IP de ton RPI5
MQTT_BROKER = "192.168.179.24"
MQTT_PORT = 1883

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to MYCOM Broker ({MQTT_BROKER})")
        # Le symbole '#' permet de s'abonner à TOUS les topics possibles
        client.subscribe("#")
        print("Subscribed to all topics (#). Waiting for data...\n")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    # Affiche le topic et la donnée brute
    print(f"Topic: {msg.topic}")
    print(f"Payload: {msg.payload.decode()}")
    print("-" * 30)

# Initialisation du client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    # Boucle infinie pour écouter les messages
    client.loop_forever()
except KeyboardInterrupt:
    print("\nSniffer stopped.")
except Exception as e:
    print(f"Error: {e}")