import 'package:flutter/material.dart';

void main() {
  runApp(const EcoMonitorApp());
}

class EcoMonitorApp extends StatelessWidget {
  const EcoMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Global Campus Eco-Monitor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.light,
        primarySwatch: Colors.green,
        useMaterial3: true,
      ),
      home: const DashboardPage(),
    );
  }
}

// Modèle de données pour une salle
class RoomData {
  final String id; // F1:R1
  final String name; // Kitchen
  double temp;
  double humidity;
  double co2;
  double watts;
  bool isOccupied;
  bool windowOpen;
  bool heaterOn;
  bool lightOn;

  RoomData({
    required this.id,
    required this.name,
    this.temp = 0,
    this.humidity = 0,
    this.co2 = 0,
    this.watts = 0,
    this.isOccupied = false,
    this.windowOpen = false,
    this.heaterOn = false,
    this.lightOn = false,
  });
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  // Simulation de la structure dynamique reçue par MQTT
  final Map<String, RoomData> rooms = {
    'F1:R1': RoomData(id: 'F1:R1', name: 'Kitchen', temp: 22.5, humidity: 45, co2: 410, watts: 150, isOccupied: true, heaterOn: true),
    'F1:R2': RoomData(id: 'F1:R2', name: 'Office A', temp: 19.0, humidity: 50, co2: 380, watts: 45, windowOpen: true),
    'F2:R1': RoomData(id: 'F2:R1', name: 'Meeting Room', temp: 21.0, humidity: 40, co2: 850, watts: 300, isOccupied: true, lightOn: true),
    'F2:R2': RoomData(id: 'F2:R2', name: 'Lounge', temp: 20.5, humidity: 48, co2: 400, watts: 10),
  };

  @override
  Widget build(BuildContext context) {
    // Extraction unique des étages (F1, F2...)
    final floors = rooms.keys.map((id) => id.split(':').first).toSet().toList()..sort();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Global Campus - Sendai'),
        centerTitle: true,
        backgroundColor: Colors.green[700],
        foregroundColor: Colors.white,
      ),
      body: ListView.builder(
        padding: const EdgeInsets.symmetric(vertical: 10),
        itemCount: floors.length,
        itemBuilder: (context, index) {
          String floor = floors[index];
          return _buildFloorFolder(floor);
        },
      ),
    );
  }

  Widget _buildFloorFolder(String floorCode) {
    final floorRooms = rooms.values.where((r) => r.id.startsWith(floorCode)).toList();

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: ExpansionTile(
        leading: const Icon(Icons.folder_special, color: Colors.amber),
        title: Text('Floor $floorCode', style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text('${floorRooms.length} rooms monitored'),
        children: floorRooms.map((room) => ListTile(
          leading: const Icon(Icons.meeting_room_outlined),
          title: Text(room.name),
          subtitle: Text(room.id),
          trailing: const Icon(Icons.chevron_right),
          onTap: () {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => RoomDetailPage(room: room)),
            );
          },
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
      appBar: AppBar(
        title: Text('${widget.room.id}: ${widget.room.name}'),
        backgroundColor: Colors.green[600],
        foregroundColor: Colors.white,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            // Section Indicateurs Numériques
            _buildSensorCard('Temperature', '${widget.room.temp}°C', Icons.thermostat, Colors.orange, 'TEMP'),
            _buildSensorCard('Humidity', '${widget.room.humidity}%', Icons.water_drop, Colors.blue, 'HUM'),
            _buildSensorCard('CO2 Level', '${widget.room.co2} ppm', Icons.cloud, Colors.blueGrey, 'CO2'),
            _buildSensorCard('Power Usage', '${widget.room.watts} W', Icons.bolt, Colors.amber, 'WATTS'),
            
            const SizedBox(height: 20),
            const Divider(),
            const SizedBox(height: 10),

            // Section Interrupteurs/États
            Wrap(
              spacing: 15,
              runSpacing: 15,
              alignment: WrapAlignment.center,
              children: [
                _buildStatusIndicator('Occupied', widget.room.isOccupied, Icons.person),
                _buildStatusIndicator('Window', widget.room.windowOpen, Icons.window, activeLabel: 'OPEN', inactiveLabel: 'CLOSED'),
                _buildStatusIndicator('Heater', widget.room.heaterOn, Icons.heat_pump),
                _buildStatusIndicator('Light', widget.room.lightOn, Icons.lightbulb),
              ],
            ),

            // Zone d'affichage du graphique dynamique
            if (activeGraph != null) ...[
              const SizedBox(height: 30),
              _buildGraphPlaceholder(),
            ]
          ],
        ),
      ),
    );
  }

  Widget _buildSensorCard(String label, String value, IconData icon, Color color, String graphKey) {
    bool isSelected = activeGraph == graphKey;

    return Card(
      elevation: isSelected ? 4 : 1,
      margin: const EdgeInsets.only(bottom: 10),
      color: isSelected ? Colors.green[50] : null,
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: color.withOpacity(0.1),
          child: Icon(icon, color: color),
        ),
        title: Text(label),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(value, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
            const SizedBox(width: 10),
            IconButton(
              icon: Icon(Icons.show_chart, color: isSelected ? Colors.green : Colors.grey),
              onPressed: () {
                setState(() {
                  activeGraph = (activeGraph == graphKey) ? null : graphKey;
                });
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusIndicator(String label, bool isOn, IconData icon, {String? activeLabel, String? inactiveLabel}) {
    return Container(
      width: 150,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isOn ? Colors.green[100] : Colors.red[50],
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: isOn ? Colors.green : Colors.red),
      ),
      child: Row(
        children: [
          Icon(icon, color: isOn ? Colors.green[800] : Colors.red[800]),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: const TextStyle(fontSize: 12)),
                Text(
                  isOn ? (activeLabel ?? 'ON') : (inactiveLabel ?? 'OFF'),
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
              ],
            ),
          )
        ],
      ),
    );
  }

  Widget _buildGraphPlaceholder() {
    return Container(
      height: 250,
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(15),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)],
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text('Live Timeline: $activeGraph', style: const TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 20),
          const Icon(Icons.auto_graph, size: 80, color: Colors.green),
          const SizedBox(height: 10),
          const Text('Visualisation des données temporelles...', style: TextStyle(color: Colors.grey, fontSize: 12)),
        ],
      ),
    );
  }
}