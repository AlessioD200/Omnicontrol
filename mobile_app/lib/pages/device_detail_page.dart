import 'package:flutter/material.dart';
import '../models/device.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';
import 'device_commands_page.dart';
import 'device_camera_page.dart';
import 'pairing/samsung_pairing.dart';

class DeviceDetailPage extends StatelessWidget {
  final OmnicontrolDevice device;
  const DeviceDetailPage({super.key, required this.device});

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          Expanded(child: Text(device.name)),
          if (device.paired)
            const Padding(
              padding: EdgeInsets.only(left: 8.0),
              child: Icon(Icons.check_circle, color: Colors.green, size: 18),
            ),
        ]),
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Top row: address and paired indicator
              Row(children: [
                Expanded(child: Text('Address: ${device.address}')),
                if (device.paired) const Icon(Icons.check_circle, color: Colors.green, size: 18),
              ]),
              const SizedBox(height: 12),
              // Action buttons row
              Row(children: [
                ElevatedButton(
                  onPressed: () async {
                    try {
                      await prov.toggle(device.id);
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Toggled')));
                    } catch (e) {
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Toggle failed: $e')));
                    }
                  },
                  child: const Text('Toggle'),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: () async {
                    try {
                      await prov.ping(device.id);
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ping sent')));
                    } catch (e) {
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ping failed: $e')));
                    }
                  },
                  child: const Text('Ping'),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: () {
                    Navigator.push(context, MaterialPageRoute(builder: (_) => DeviceCameraPage(deviceId: device.id)));
                  },
                  child: const Text('View Camera'),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: () async {
                    final initial = <String, dynamic>{};
                    final found = prov.devices.firstWhere((d) => d.id == device.id, orElse: () => device);
                    final meta = found.metadata ?? {};
                    if (meta.containsKey('ble_commands_map') && meta['ble_commands_map'] is Map) {
                      initial.addAll(Map<String, dynamic>.from(meta['ble_commands_map'] as Map));
                    }
                    final res = await Navigator.push(context, MaterialPageRoute(builder: (_) => DeviceCommandsPage(deviceId: device.id, initial: initial)));
                    if (res == true) {
                      if (!context.mounted) return;
                      await prov.refresh();
                    }
                  },
                  child: const Text('Edit commands'),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: () async {
                    final res = await Navigator.push(context, MaterialPageRoute(builder: (_) => SamsungPairingPage(deviceId: device.id, initialIp: (device.metadata ?? {})['samsung_ip'] ?? '', initialName: (device.metadata ?? {})['samsung_remote_name'] ?? '')));
                    if (res == true) {
                      if (!context.mounted) return;
                      await prov.refresh();
                    }
                  },
                  child: const Text('Pair SmartView'),
                ),
              ]),
              const SizedBox(height: 18),
              // Remote control section
              if (device.address.isNotEmpty && (device.address.contains(':') || RegExp(r'^[0-9A-Fa-f:._-]{5,}$').hasMatch(device.address)))
                Column(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
                      ElevatedButton(
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'menu');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Menu')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Menu failed: $e')));
                          }
                        },
                        child: const Text('Menu'),
                      ),
                      ElevatedButton(
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'source');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Source')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Source failed: $e')));
                          }
                        },
                        child: const Text('Source'),
                      ),
                      ElevatedButton(
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'vol_down');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vol -')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Volume failed: $e')));
                          }
                        },
                        child: const Icon(Icons.volume_down),
                      ),
                      ElevatedButton(
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'vol_up');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vol +')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Volume failed: $e')));
                          }
                        },
                        child: const Icon(Icons.volume_up),
                      ),
                    ]),
                    const SizedBox(height: 12),
                    // D-pad
                    Column(children: [
                      IconButton(
                        iconSize: 36,
                        icon: const Icon(Icons.keyboard_arrow_up),
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'up');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Up')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Up failed: $e')));
                          }
                        },
                      ),
                      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                        IconButton(
                          iconSize: 36,
                          icon: const Icon(Icons.keyboard_arrow_left),
                          onPressed: () async {
                            try {
                              await prov.remote(device.id, 'left');
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Left')));
                            } catch (e) {
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Left failed: $e')));
                            }
                          },
                        ),
                        ElevatedButton(
                          onPressed: () async {
                            try {
                              await prov.remote(device.id, 'ok');
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('OK')));
                            } catch (e) {
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('OK failed: $e')));
                            }
                          },
                          child: const Icon(Icons.check),
                        ),
                        IconButton(
                          iconSize: 36,
                          icon: const Icon(Icons.keyboard_arrow_right),
                          onPressed: () async {
                            try {
                              await prov.remote(device.id, 'right');
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Right')));
                            } catch (e) {
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Right failed: $e')));
                            }
                          },
                        ),
                      ]),
                      IconButton(
                        iconSize: 36,
                        icon: const Icon(Icons.keyboard_arrow_down),
                        onPressed: () async {
                          try {
                            await prov.remote(device.id, 'down');
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Down')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Down failed: $e')));
                          }
                        },
                      ),
                    ])
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }
}
