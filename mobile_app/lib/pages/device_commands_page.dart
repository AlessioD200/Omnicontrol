import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';

class DeviceCommandsPage extends StatefulWidget {
  final String deviceId;
  final Map<String, dynamic> initial;
  const DeviceCommandsPage({super.key, required this.deviceId, required this.initial});

  @override
  State<DeviceCommandsPage> createState() => _DeviceCommandsPageState();
}

class _DeviceCommandsPageState extends State<DeviceCommandsPage> {
  final Map<String, TextEditingController> _controllers = {};
  final List<String> actions = ['menu','source','vol_down','vol_up','up','down','left','right','ok'];

  @override
  void initState(){
    super.initState();
    for (final a in actions) {
      _controllers[a] = TextEditingController(text: widget.initial[a] ?? '');
    }
  }

  @override
  void dispose(){
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context){
    final prov = Provider.of<OmniProvider>(context, listen: false);
    return Scaffold(
      appBar: AppBar(title: const Text('Edit Command Mapping')),
      body: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(children: [
          Expanded(
            child: ListView(
              children: actions.map((a) => ListTile(
                title: Text(a),
                subtitle: TextField(controller: _controllers[a], decoration: InputDecoration(hintText: 'command id')),
              )).toList(),
            ),
          ),
          ElevatedButton(
            onPressed: () async {
              final mapping = <String,String>{};
              for (final a in actions) {
                final v = _controllers[a]!.text.trim();
                if (v.isNotEmpty) {
                  mapping[a] = v;
                }
              }
              try{
                await prov.api.sendCommand(widget.deviceId, {'command': 'noop'}); // keep usage alive
                // Save metadata: store mapping under metadata.ble_commands_map
                await prov.api.postDeviceMetadata(widget.deviceId, {'ble_commands_map': mapping});
                if (!context.mounted) return;
                Navigator.of(context).pop(true);
              }catch(e){
                if (!context.mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Save failed: $e')));
              }
            },
            child: const Text('Save'),
          )
          ,
          const SizedBox(height:8),
          ElevatedButton(
            onPressed: () async {
              try {
                final prov = Provider.of<OmniProvider>(context, listen: false);
                final url = '${prov.api.baseUrl}/api/devices/${widget.deviceId}/snapshot';
                // show dialog with image
                if (!context.mounted) return;
                showDialog(context: context, builder: (ctx) => AlertDialog(
                  content: SizedBox(width: 320, height: 240, child: Image.network(url, errorBuilder: (c,e,s) => Center(child: Text('Snapshot failed: $e')))),
                  actions: [TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Close'))],
                ));
              } catch (e) {
                if (!context.mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Snapshot failed: $e')));
              }
            },
            child: const Text('Take snapshot'),
          ),
        ]),
      ),
    );
  }
}
