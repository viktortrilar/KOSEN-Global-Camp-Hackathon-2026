import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';
import 'package:http/http.dart' as http;
import 'package:fl_chart/fl_chart.dart';

void main() {
  runApp(const EcoMonitorApp());
}

class MycomColors {
  static const Color red = Color(0xFFD50032);
  static const Color black = Color(0xFF111111);
  static const Color white = Color(0xFFFFFFFF);
  static const Color borderGrey = Color(0xFFDDDDDD);
  static const Color connectionGreen = Color(0xFF00C853);
}

class EcoMonitorApp extends StatelessWidget {
  const EcoMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Cool-Watcher | MYCOM',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: const ColorScheme.light(
          primary: MycomColors.red,
          secondary: MycomColors.black,
        ),
        scaffoldBackgroundColor: MycomColors.white,
        appBarTheme: const AppBarTheme(
          backgroundColor: MycomColors.white,
          foregroundColor: MycomColors.black,
          elevation: 0,
          shape: Border(bottom: BorderSide(color: MycomColors.red, width: 4)),
        ),
        cardTheme: const CardThemeData(
          elevation: 0,
          shape: RoundedRectangleBorder(
            side: BorderSide(color: MycomColors.borderGrey, width: 1),
            borderRadius: BorderRadius.zero,
          ),
          margin: EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          color: MycomColors.white,
        ),
      ),
      home: const DashboardPage(),
    );
  }
}

class RoomData {
  final String id;
  final String name;
  double temp = 0, humidity = 0, co2 = 0, watts = 0;
  bool isOccupied = false, windowOpen = false, heaterOn = false, lightOn = false;

  RoomData({required this.id, required this.name});
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
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
    client.keepAlivePeriod = 20;

    final connMess = MqttConnectMessage()
        .withClientIdentifier('flutter_client_${DateTime.now().millisecondsSinceEpoch}')
        .startClean()
        .withWillQos(MqttQos.atLeastOnce);
    client.connectionMessage = connMess;

    try {
      await client.connect();
    } catch (e) {
      client.disconnect();
    }

    if (client.connectionStatus!.state == MqttConnectionState.connected) {
      client.subscribe("#", MqttQos.atMostOnce);
      client.updates!.listen((List<MqttReceivedMessage<MqttMessage>> c) {
        final MqttPublishMessage recMess = c[0].payload as MqttPublishMessage;
        final String pt = MqttPublishPayload.bytesToStringAsString(recMess.payload.message);
        _parseMqttData(c[0].topic, pt);
      });
    }
  }

  void _parseMqttData(String topic, String value) {
    List<String> parts = topic.split('/');
    if (parts.length < 3 || parts[0] != 'room') return;

    String roomId = parts[1];
    String dataType = parts[2];

    setState(() {
      if (!rooms.containsKey(roomId)) {
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
          final openings = payload['openings'] as Map<String, dynamic>;
          if (openings.containsKey('window')) room.windowOpen = openings['window'] == 'open';
        }
      } catch (e) { /* silent fail */ }
    });
  }

  @override
  Widget build(BuildContext context) {
    final roomList = rooms.values.toList();
    bool isConnected = client.connectionStatus?.state == MqttConnectionState.connected;

    return Scaffold(
      appBar: AppBar(
        title: const Text('COOL-WATCHER', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.5)),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Text(
                  isConnected ? "NETWORK OK" : "OFFLINE", 
                  style: TextStyle(
                    color: isConnected ? MycomColors.connectionGreen : MycomColors.red, 
                    fontWeight: FontWeight.bold, fontSize: 12
                  )
                ),
                const SizedBox(width: 8),
                Container(width: 8, height: 8, color: isConnected ? MycomColors.connectionGreen : MycomColors.red),
              ],
            ),
          ),
        ],
      ),
      body: rooms.isEmpty 
        ? const Center(child: Text("WAITING FOR DATA FROM SENDAL LAB...", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)))
        : ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: 16),
            itemCount: roomList.length,
            itemBuilder: (context, index) {
              final room = roomList[index];
              return Card(
                child: ListTile(
                  title: Text(room.name.toUpperCase(), style: const TextStyle(fontWeight: FontWeight.w900)),
                  subtitle: Text('ID: ${room.id} • ${room.isOccupied ? "ACTIVE" : "IDLE"}'),
                  trailing: const Icon(Icons.arrow_forward, color: MycomColors.black),
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
    setState(() { activeGraph = sensorKey; isLoadingChart = true; chartPoints = []; });
    String apiSensor = {'TEMP': 'temperature', 'HUM': 'humidity', 'CO2': 'co2', 'WATTS': 'power'}[sensorKey] ?? "";
    
    try {
      final url = Uri.parse('http://192.168.179.24:8000/rooms/${widget.room.id}/history/$apiSensor?hours=1');
      final response = await http.get(url);
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        List<dynamic> history = data['data'] ?? [];
        if (history.length > 360) history = history.sublist(history.length - 360);
        
        List<FlSpot> points = [];
        for (int i = 0; i < history.length; i++) {
          points.add(FlSpot(i.toDouble(), (history[i]['value'] as num).toDouble()));
        }
        setState(() { chartPoints = points; isLoadingChart = false; });
      }
    } catch (e) { setState(() => isLoadingChart = false); }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.room.name.toUpperCase(), style: const TextStyle(fontWeight: FontWeight.w900))),
      body: SingleChildScrollView(
        child: Column(
          children: [
            Container(
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: MycomColors.borderGrey, width: 1)),
              ),
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  _statusBlock('AC UNIT', widget.room.heaterOn),
                  _statusBlock('WINDOW', widget.room.windowOpen),
                  _statusBlock('OCCUPANCY', widget.room.isOccupied),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                children: [
                  _buildMetricTile('TEMPERATURE', '${widget.room.temp}', '°C', 'TEMP'),
                  _buildMetricTile('HUMIDITY', '${widget.room.humidity}', '%', 'HUM'),
                  _buildMetricTile('CO2 LEVEL', '${widget.room.co2}', ' PPM', 'CO2'),
                  _buildMetricTile('POWER LOAD', '${widget.room.watts}', ' W', 'WATTS'),
                  if (activeGraph != null) _buildGraphSection(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusBlock(String label, bool isActive) {
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          color: isActive ? MycomColors.red : MycomColors.black,
          child: Text(
            isActive ? 'ACTIVE' : 'INACTIVE', 
            style: const TextStyle(color: MycomColors.white, fontWeight: FontWeight.bold, fontSize: 10)
          ),
        ),
        const SizedBox(height: 8),
        Text(label, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 0.5)),
      ],
    );
  }

  Widget _buildMetricTile(String title, String val, String unit, String key) {
    bool isSelected = activeGraph == key;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: isSelected ? MycomColors.red.withValues(alpha: 0.05) : MycomColors.white,
        border: Border.all(color: isSelected ? MycomColors.red : MycomColors.borderGrey, width: isSelected ? 2 : 1),
      ),
      child: ListTile(
        title: Text(title, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
        subtitle: Text('$val$unit', style: const TextStyle(color: MycomColors.black, fontSize: 26, fontWeight: FontWeight.bold)),
        trailing: IconButton(
          icon: Icon(isSelected ? Icons.close : Icons.analytics_outlined, color: isSelected ? MycomColors.red : MycomColors.black),
          onPressed: () => isSelected ? setState(() => activeGraph = null) : _loadChartData(key),
        ),
      ),
    );
  }

  Widget _buildGraphSection() {
    return Container(
      height: 250,
      margin: const EdgeInsets.only(top: 20),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(border: Border.all(color: MycomColors.black, width: 2)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("TREND ANALYSIS : $activeGraph", style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
          const SizedBox(height: 10),
          Expanded(
            child: isLoadingChart 
              ? const Center(child: CircularProgressIndicator(color: MycomColors.red)) 
              : LineChart(_buildChartData()),
          ),
        ],
      ),
    );
  }

  LineChartData _buildChartData() {
    return LineChartData(
      gridData: const FlGridData(show: true, drawVerticalLine: false),
      titlesData: const FlTitlesData(show: false),
      borderData: FlBorderData(show: false),
      lineBarsData: [
        LineChartBarData(
          spots: chartPoints,
          isCurved: false,
          color: MycomColors.red,
          barWidth: 3,
          dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(show: true, color: MycomColors.red.withValues(alpha: 0.1)),
        ),
      ],
    );
  }
}