import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';
import 'package:http/http.dart' as http;
import 'package:fl_chart/fl_chart.dart';

void main() {
  runApp(const EcoMonitorApp());
}

class EcoMonitorApp extends StatelessWidget {
  const EcoMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Global Campus Sendai - Cool-Watcher',
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
    // Format attendu: room/sendai_lab/sensors ou room/sendai_lab/openings
    List<String> parts = topic.split('/');
    if (parts.length < 3 || parts[0] != 'room') {
      return;
    }

    String roomId = parts[1];
    String dataType = parts[2]; // 'sensors' ou 'openings'

    setState(() {
      if (!rooms.containsKey(roomId)) {
        // Formatage du nom: "sendai_lab" -> "Sendai Lab"
        String roomName = roomId.split('_').map((w) => w[0].toUpperCase() + w.substring(1)).join(' ');
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
    final roomList = rooms.values.toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Global Campus Cool-Watcher'),
        actions: [
          Icon(Icons.circle, color: client.connectionStatus?.state == MqttConnectionState.connected ? Colors.green : Colors.red),
          const SizedBox(width: 15),
        ],
      ),
      body: rooms.isEmpty 
        ? const Center(child: Text("Waiting for MQTT data from RPI5..."))
        : ListView.builder(
            itemCount: roomList.length,
            itemBuilder: (context, index) {
              final room = roomList[index];
              return Card(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ListTile(
                  leading: const Icon(Icons.meeting_room, color: Colors.orange),
                  title: Text(room.name),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (context) => RoomDetailPage(room: room))),
                ),
              );
            },
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
  List<FlSpot> chartPoints = [];
  bool isLoadingChart = false;

  Future<void> _loadChartData(String sensorKey) async {
    setState(() {
      activeGraph = sensorKey;
      isLoadingChart = true;
      chartPoints = [];
    });

    // Traduction de la clé UI vers le nom attendu par l'API REST
    String apiSensor = "";
    switch (sensorKey) {
      case 'TEMP': apiSensor = 'temperature'; break;
      case 'HUM': apiSensor = 'humidity'; break;
      case 'CO2': apiSensor = 'co2'; break;
      case 'WATTS': apiSensor = 'power'; break;
      default:
        setState(() => isLoadingChart = false);
        return;
    }

    try {
      // On demande 1 heure entière pour éviter les erreurs de décimales dans l'API
      final url = Uri.parse('http://192.168.179.24:8000/rooms/${widget.room.id}/history/$apiSensor?hours=1');
      final response = await http.get(url);
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        List<dynamic> history = data['data'] ?? [];
        
        // Le simulateur envoie 1 point toutes les 5 secondes (12 points/minute)
        // 30 minutes = 360 points. On coupe la liste pour ne garder que la fin !
        if (history.length > 360) {
          history = history.sublist(history.length - 360);
        }
        
        List<FlSpot> points = [];
        double x = 0;
        for (var item in history) {
          points.add(FlSpot(x, (item['value'] as num).toDouble()));
          x += 1;
        }
        
        setState(() {
          chartPoints = points;
          isLoadingChart = false;
        });
      } else {
        setState(() => isLoadingChart = false);
      }
    } catch (e) {
      print('Error fetching history: $e');
      setState(() => isLoadingChart = false);
    }
  }

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
                height: 250, 
                width: double.infinity, 
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.05),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.all(8.0),
                    child: Text("30m History: $activeGraph", style: const TextStyle(fontWeight: FontWeight.bold)),
                    ),
                    Expanded(
                      child: isLoadingChart 
                        ? const Center(child: CircularProgressIndicator())
                        : chartPoints.isEmpty 
                          ? const Center(child: Text("No historical data available."))
                          : Padding(
                              padding: const EdgeInsets.all(16.0),
                              child: LineChart(_buildChartData()),
                            ),
                    ),
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
            onPressed: () {
              if (activeGraph == key) {
                setState(() => activeGraph = null);
              } else {
                _loadChartData(key);
              }
            },
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

  LineChartData _buildChartData() {
    return LineChartData(
      gridData: const FlGridData(show: true),
      titlesData: const FlTitlesData(
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)), // Cache les X pour un design épuré
        topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
      ),
      borderData: FlBorderData(show: true),
      lineBarsData: [
        LineChartBarData(
          spots: chartPoints,
          isCurved: true,
          color: Colors.green,
          barWidth: 3,
          dotData: const FlDotData(show: false),
        ),
      ],
    );
  }
}