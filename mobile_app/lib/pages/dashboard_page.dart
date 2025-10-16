import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        actions: [
          IconButton(
            icon: const Icon(Icons.login),
            onPressed: () => Navigator.pushNamed(context, '/login'),
            tooltip: 'Link hub to account',
          )
        ],
      ),
      body: RefreshIndicator(
        onRefresh: prov.refresh,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Hub status', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Row(children: [
                    prov.connected ? const Icon(Icons.check_circle, color: Colors.green) : const Icon(Icons.error, color: Colors.red),
                    const SizedBox(width: 8),
                    Text(prov.connected ? 'Connected' : 'Not connected'),
                    const Spacer(),
                    ElevatedButton(onPressed: prov.checkConnection, child: const Text('Verify')),
                  ]),
                  const SizedBox(height: 8),
                  Text('Hub info: ${prov.hubInfo ?? {}}'),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('System', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Text('Linked account: ${prov.linkedAccount ?? 'None'}'),
                  const SizedBox(height: 6),
                  Text('Selected hub: ${prov.selectedHub ?? 'None'}'),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Firmware', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  ElevatedButton(
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
                      child: const Text('Check for firmware updates')),
                ]),
              ),
            ),
            const SizedBox(height: 24),
            if (prov.lastError != null) Text('Last error: ${prov.lastError}', style: const TextStyle(color: Colors.red)),
          ],
        ),
      ),
    );
  }
}
