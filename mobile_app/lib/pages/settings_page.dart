import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context);
    _controller.text = prov.api.baseUrl;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: ListView(
          children: [
            TextField(controller: _controller, decoration: const InputDecoration(labelText: 'Hub base URL (http://ip:8000)')),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: () async {
                final url = _controller.text.trim();
                prov.api.setBaseUrl(url);
                await prov.checkConnection();
                if (!mounted) return;
                final wasConnected = prov.connected;
                final errorText = prov.lastError;
                if (wasConnected) {
                  final prefs = await SharedPreferences.getInstance();
                  await prefs.setString('hub_base_url', url);
                  if (!mounted) return;
                  _showSnackBar('Connected and saved');
                } else {
                  _showSnackBar('Failed to connect: $errorText');
                }
              },
              child: const Text('Save and Connect'),
            ),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                title: const Text('Account'),
                subtitle: Text(prov.linkedAccount ?? 'Not linked'),
                trailing: ElevatedButton(onPressed: () => Navigator.pushNamed(context, '/login'), child: const Text('Link')),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                title: const Text('Preferences'),
                subtitle: const Text('Customize hub behavior, scans and notifications'),
                trailing: ElevatedButton(onPressed: () {}, child: const Text('Edit')),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                title: const Text('Device list'),
                subtitle: const Text('Hide noisy unnamed MAC-only devices'),
                trailing: Switch(
                  value: prov.hideNoisyDevices,
                  onChanged: (v) async {
                    prov.hideNoisyDevices = v;
                    final prefs = await SharedPreferences.getInstance();
                    await prefs.setBool('hide_noisy_devices', v);
                    prov.refresh();
                  },
                ),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                title: const Text('Firmware updates'),
                subtitle: const Text('Check for hub firmware releases'),
                trailing: ElevatedButton(
                    onPressed: () async {
                      try {
                        final fw = await prov.checkFirmware();
                        if (!context.mounted) return;
                        showDialog(context: context, builder: (ctx) => AlertDialog(title: const Text('Latest firmware'), content: Text(fw.toString()), actions: [TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('OK'))]));
                      } catch (e) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Firmware check failed: $e')));
                      }
                    },
                    child: const Text('Check')),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                title: const Text('Hub settings refresh'),
                subtitle: const Text('Force refresh hub info and devices list'),
                trailing: ElevatedButton(onPressed: prov.refresh, child: const Text('Refresh')),
              ),
            ),
            const SizedBox(height: 12),
            if (prov.lastError != null) Padding(padding: const EdgeInsets.symmetric(vertical: 8.0), child: Text('Last error: ${prov.lastError}', style: const TextStyle(color: Colors.red))),
          ],
        ),
      ),
    );
  }

  void _showSnackBar(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }
}
