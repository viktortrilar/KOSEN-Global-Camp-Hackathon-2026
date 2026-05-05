import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';

void main() {
  runApp(const EcoMonitorApp());
}

class EcoMonitorApp extends StatelessWidget {
  const EcoMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Global Campus Sendai - EcoMonitor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(primarySwatch: Colors.green, useMaterial3: true),
      home: const DashboardPage(),
    );
  }
}

class RoomData {
  final String id;
  final String name;
  double temp = 0;
  double humidity = 0;
  double co2 = 0;
  double watts = 0;
  bool isOccupied = false;
  bool windowOpen = false;
  bool heaterOn = false;
  bool lightOn = false;

  RoomData({required this.id, required this.name});
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  // Configuration MQTT - REMPLACE PAR L'IP DE TON RPI5
  final String brokerIp = "192.168.179.24"; 
  late MqttServerClient client;
  Map<String, RoomData> rooms = {};

  @override
  void initState() {
    super.initState();
    _setupMqtt();
  }

  Future<void> _setupMqtt() async {
    client = MqttServerClient(brokerIp, 'flutter_client_${DateTime.now().millisecondsSinceEpoch}');
    client.port = 1883;
    client.logging(on: true); // Active les logs détaillés de la connexion MQTT
    client.keepAlivePeriod = 20;
    client.onDisconnected = () => print('MQTT: Disconnected');

    final connMess = MqttConnectMessage()
        .withClientIdentifier('flutter_client_${DateTime.now().millisecondsSinceEpoch}')
        .startClean()
        .withWillQos(MqttQos.atLeastOnce);
    client.connectionMessage = connMess;

    try {
      await client.connect();
    } catch (e) {
      print('MQTT: Connection failed - $e');
      client.disconnect();
    }

    if (client.connectionStatus!.state == MqttConnectionState.connected) {
      print('MQTT: Connected to RPI5');
      // Souscription au wildcard pour recevoir toutes les données des salles
      // Format attendu: F1/R1/Kitchen/TEMP
      client.subscribe("#", MqttQos.atMostOnce);

      client.updates!.listen((List<MqttReceivedMessage<MqttMessage>> c) {
        final MqttPublishMessage recMess = c[0].payload as MqttPublishMessage;
        final String pt = MqttPublishPayload.bytesToStringAsString(recMess.payload.message);
        final String topic = c[0].topic;

        print('DEBUG MQTT -> Topic: $topic, Payload: $pt');

        _parseMqttData(topic, pt);
      });
    }
  }

  void _parseMqttData(String topic, String value) {
    // Expected format from simulator: room/{room_id}/sensors OR room/{room_id}/openings
    List<String> parts = topic.split('/');
    if (parts.length < 3 || parts[0] != 'room') {
      print('MQTT: Ignored topic - $topic');
      return;
    }

    String baseRoomId = parts[1];
    String dataType = parts[2]; // 'sensors' or 'openings'

    // Ajout d'un étage par défaut (F1) pour conserver le design des dossiers
    String floorCode = "F1";
    String roomId = "$floorCode:$baseRoomId";

    setState(() {
      if (!rooms.containsKey(roomId)) {
        // Format the room ID into a readable name (e.g., sendai_lab -> Sendai Lab)
        String roomName = baseRoomId.split('_').map((w) => w[0].toUpperCase() + w.substring(1)).join(' ');
        rooms[roomId] = RoomData(id: roomId, name: roomName);
      }

      final room = rooms[roomId]!;
      
      try {
        final Map<String, dynamic> payload = jsonDecode(value);
        
        if (dataType == 'sensors') {
          if (payload.containsKey('temperature')) room.temp = (payload['temperature'] as num).toDouble();
          if (payload.containsKey('humidity')) room.humidity = (payload['humidity'] as num).toDouble();
          if (payload.containsKey('co2')) room.co2 = (payload['co2'] as num).toDouble();
          if (payload.containsKey('power')) room.watts = (payload['power'] as num).toDouble();
          if (payload.containsKey('occupied')) room.isOccupied = payload['occupied'] as bool;
          if (payload.containsKey('ac_on')) room.heaterOn = payload['ac_on'] as bool;
        } else if (dataType == 'openings') {
          if (payload.containsKey('openings')) {
            final openings = payload['openings'] as Map<String, dynamic>;
            if (openings.containsKey('window')) room.windowOpen = openings['window'] == 'open';
          }
        }
      } catch (e) {
        print('MQTT: Failed to parse JSON payload - $e');
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final floors = rooms.keys.map((id) => id.split(':').first).toSet().toList()..sort();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Global Campus Eco-Monitor'),
        actions: [
          Icon(Icons.circle, color: client.connectionStatus?.state == MqttConnectionState.connected ? Colors.green : Colors.red),
          const SizedBox(width: 15),
        ],
      ),
      body: rooms.isEmpty 
        ? const Center(child: Text("Waiting for MQTT data from RPI5..."))
        : ListView.builder(
            itemCount: floors.length,
            itemBuilder: (context, index) => _buildFloorFolder(floors[index]),
          ),
    );
  }

  Widget _buildFloorFolder(String floorCode) {
    final floorRooms = rooms.values.where((r) => r.id.startsWith(floorCode)).toList();
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: ExpansionTile(
        leading: const Icon(Icons.folder, color: Colors.orange),
        title: Text('Floor $floorCode'),
        children: floorRooms.map((room) => ListTile(
          title: Text(room.name),
          subtitle: Text(room.id),
          onTap: () => Navigator.push(context, MaterialPageRoute(builder: (context) => RoomDetailPage(room: room))),
        )).toList(),
      ),
    );
  }
}

class RoomDetailPage extends StatefulWidget {
  final RoomData room;
  const RoomDetailPage({super.key, required this.room});

  @override
  State<RoomDetailPage> createState() => _RoomDetailPageState();
}

class _RoomDetailPageState extends State<RoomDetailPage> {
  String? activeGraph;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${widget.room.id}: ${widget.room.name}')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            _buildDataTile('Temperature', '${widget.room.temp}°C', Icons.thermostat, Colors.orange, 'TEMP'),
            _buildDataTile('Humidity', '${widget.room.humidity}%', Icons.water_drop, Colors.blue, 'HUM'),
            _buildDataTile('CO2', '${widget.room.co2} ppm', Icons.cloud, Colors.blueGrey, 'CO2'),
            _buildDataTile('Power', '${widget.room.watts} W', Icons.bolt, Colors.amber, 'WATTS'),
            const Divider(),
            _buildStatusTile('Occupancy', widget.room.isOccupied, Icons.person),
            _buildStatusTile('Window', widget.room.windowOpen, Icons.window),
            _buildStatusTile('Heater', widget.room.heaterOn, Icons.heat_pump),
            if (activeGraph != null) ...[
              const SizedBox(height: 20),
              Container(
                height: 200, 
                width: double.infinity, 
                color: Colors.black12, 
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text("Real-time Chart: $activeGraph"),
                    const Icon(Icons.show_chart, size: 50),
                  ],
                ),
              )
            ]
          ],
        ),
      ),
    );
  }

  Widget _buildDataTile(String label, String value, IconData icon, Color color, String key) {
    return ListTile(
      leading: Icon(icon, color: color),
      title: Text(label),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
          IconButton(
            icon: Icon(Icons.query_stats, color: activeGraph == key ? Colors.green : Colors.grey),
            onPressed: () => setState(() => activeGraph = activeGraph == key ? null : key),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusTile(String label, bool state, IconData icon) {
    return ListTile(
      leading: Icon(icon, color: state ? Colors.green : Colors.red),
      title: Text(label),
      trailing: Text(state ? "ON/OPEN" : "OFF/CLOSED", style: TextStyle(color: state ? Colors.green : Colors.red, fontWeight: FontWeight.bold)),
    );
  }
}