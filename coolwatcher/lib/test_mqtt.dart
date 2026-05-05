import 'dart:io';
import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';

Future<void> main() async {
  final String brokerIp = "192.168.179.24";
  final client = MqttServerClient(brokerIp, 'test_client_cli');

  client.port = 1883;
  client.logging(on: true); // Affichera tous les détails de connexion
  client.keepAlivePeriod = 20;

  final connMess = MqttConnectMessage()
      .withClientIdentifier('test_client_cli_${DateTime.now().millisecondsSinceEpoch}')
      .startClean();
  client.connectionMessage = connMess;

  print('--- TEST DE CONNEXION MQTT ---');
  print('Tentative de connexion a $brokerIp sur le port 1883...');

  try {
    await client.connect();
  } catch (e) {
    print('❌ ERREUR CRITIQUE: $e');
    client.disconnect();
    exit(-1);
  }

  if (client.connectionStatus?.state == MqttConnectionState.connected) {
    print('✅ SUCCES : Connexion au broker MQTT reussie depuis le PC !');
    client.disconnect();
    print('Deconnexion propre.');
    exit(0);
  } else {
    print('❌ ECHEC : Statut de la connexion = ${client.connectionStatus?.state}');
    client.disconnect();
    exit(-1);
  }
}