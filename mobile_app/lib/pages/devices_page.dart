import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';
import 'device_detail_page.dart';

class DevicesPage extends StatefulWidget {
  const DevicesPage({super.key});

  @override
  State<DevicesPage> createState() => _DevicesPageState();
}

class PairingStatusDialog extends StatelessWidget {
  final String jobId;
  const PairingStatusDialog({super.key, required this.jobId});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Pairing in progress', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 12),
            Builder(builder: (ctx) {
              final prov = Provider.of<OmniProvider>(context);
              final status = prov.pairingJobs[jobId] ?? 'pending';
              final inProgress = status == 'pending' || status == 'in-progress';
              return Column(children: [
                if (inProgress) const CircularProgressIndicator() else Icon(status == 'success' ? Icons.check_circle : Icons.error, color: status == 'success' ? Colors.green : Colors.red, size: 36),
                const SizedBox(height: 12),
                Text('Status: $status'),
              ]);
            }),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () {
                // allow user to dismiss if job finished or they want to cancel view
                Navigator.of(context).pop();
              },
              child: const Text('Close'),
            ),
          ],
        ),
      ),
    );
  }
}

class _DevicesPageState extends State<DevicesPage> {
  bool _initialized = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _initialized = true;
      // Schedule refresh after the current frame to avoid calling
      // notifyListeners() while widgets are building (causes "setState
      // called during build" exceptions).
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final prov = Provider.of<OmniProvider>(context, listen: false);
        prov.refresh();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Omnicontrol')),
      body: RefreshIndicator(
        onRefresh: prov.refresh,
        child: prov.loading
            ? const Center(child: CircularProgressIndicator())
            : prov.devices.isEmpty
                ? ListView(
                    children: [
                      SizedBox(height: 120),
                      const Center(child: Text('No devices found yet')),
                      const SizedBox(height: 12),
                      Center(
                        child: ElevatedButton.icon(
                          onPressed: () async {
                            try {
                              await prov.scan();
                            } catch (e) {
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Scan failed: $e')));
                            }
                          },
                          icon: const Icon(Icons.search),
                          label: const Text('Scan for devices'),
                        ),
                      ),
                    ],
                  )
                : ListView.builder(
                    itemCount: prov.devices.length,
                    itemBuilder: (ctx, i) {
                      final d = prov.devices[i];
                      final addr = d.address;
                      final isBluetooth = addr.isNotEmpty && (addr.contains(':') || RegExp(r'^[0-9A-Fa-f:._-]{5,}$').hasMatch(addr));
                      return ListTile(
                        title: Text(d.name),
                        subtitle: Text(d.address),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (isBluetooth)
                              Padding(
                                padding: const EdgeInsets.only(right: 8.0),
                                child: d.paired
                                    ? const Icon(Icons.check_circle, color: Colors.green, size: 20)
                                    : TextButton(
                                        onPressed: () async {
                                          // pairing flow
                                          final confirmed = await showDialog<bool>(
                                            context: context,
                                            builder: (ctx) => AlertDialog(
                                              title: const Text('Pair device'),
                                              content: Text('Pair ${d.name} (${d.address}) with the hub?'),
                                              actions: [
                                                TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
                                                TextButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Pair')),
                                              ],
                                            ),
                                          );
                                          if (confirmed != true) return;
                                          try {
                                            final jobId = await prov.startPairingAndWatch({
                                              'address': addr,
                                              'name': d.name,
                                              'device_id': d.id,
                                            });

                                            if (!context.mounted) return;
                                            // show progress dialog
                                            showDialog(
                                              context: context,
                                              barrierDismissible: false,
                                              builder: (ctx) => PairingStatusDialog(jobId: jobId),
                                            );

                                            // wait for completion in background, then dismiss and refresh
                                            try {
                                              await prov.waitForPairingJob(jobId, timeoutSeconds: 90);
                                              if (!context.mounted) return;
                                              Navigator.of(context, rootNavigator: true).pop();
                                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Pairing completed')));
                                            } catch (e) {
                                              if (!context.mounted) return;
                                              Navigator.of(context, rootNavigator: true).pop();
                                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Pairing failed or timed out: $e')));
                                            }
                                          } catch (e) {
                                            if (!context.mounted) return;
                                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Pairing failed: $e')));
                                          }
                                        },
                                        child: const Text('Pair'),
                                      ),
                              ),
                            IconButton(
                              icon: const Icon(Icons.chevron_right),
                              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => DeviceDetailPage(device: d))),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
      ),
      floatingActionButton: FloatingActionButton(
        child: const Icon(Icons.search),
        onPressed: () async {
          if (!prov.connected) {
            showDialog(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('Hub not connected'),
                content: const Text('Please connect your hub from the Dashboard before scanning.'),
                actions: [
                  TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('OK'))
                ],
              ),
            );
            return;
          }

          try {
            await prov.scan();
          } catch (e) {
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Scan failed: $e')));
          }
        },
      ),
    );
  }
}
