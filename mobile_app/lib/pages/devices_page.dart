import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';
import '../widgets/device_card.dart';
import 'device_detail_page.dart';
import 'pairing/pairing_wizard.dart';

class DevicesPage extends StatefulWidget {
  const DevicesPage({super.key});

  @override
  State<DevicesPage> createState() => _DevicesPageState();
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
      appBar: AppBar(
        title: const Text('Devices'),
        actions: [
          IconButton(
            tooltip: 'Pair new device',
            icon: const Icon(Icons.add_circle_outline),
            onPressed: () {
              showModalBottomSheet(
                context: context,
                isScrollControlled: true,
                useSafeArea: true,
                builder: (_) => const PairingWizardSheet(),
              );
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: prov.refresh,
        child: prov.loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.only(bottom: 120),
                children: [
                  if (!prov.connected)
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Card(
                        color: Theme.of(context).colorScheme.errorContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(16.0),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Hub disconnected', style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer, fontWeight: FontWeight.w600)),
                              const SizedBox(height: 8),
                              Text('Reconnect your hub from the Dashboard or onboarding flow to manage devices.', style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer)),
                            ],
                          ),
                        ),
                      ),
                    ),
                  if (prov.devices.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
                      child: Column(
                        children: [
                          const Icon(Icons.devices_other_outlined, size: 64),
                          const SizedBox(height: 16),
                          const Text('No devices yet', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 8),
                          const Text('Pair a Bluetooth device or register an IP camera to get started.'),
                          const SizedBox(height: 16),
                          FilledButton.icon(
                            onPressed: () {
                              showModalBottomSheet(
                                context: context,
                                isScrollControlled: true,
                                useSafeArea: true,
                                builder: (_) => const PairingWizardSheet(),
                              );
                            },
                            icon: const Icon(Icons.add),
                            label: const Text('Launch pairing wizard'),
                          ),
                        ],
                      ),
                    ),
                  ...prov.devices.map((device) {
                    final addr = device.address;
                    final isBluetooth = addr.isNotEmpty && (addr.contains(':') || RegExp(r'^[0-9A-Fa-f:._-]{5,}$').hasMatch(addr));
                    return DeviceCard(
                      device: device,
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => DeviceDetailPage(device: device))),
                      primaryActionLabel: device.paired ? null : 'Pair',
                      onPrimaryAction: !isBluetooth || device.paired
                          ? null
                          : () {
                              showModalBottomSheet(
                                context: context,
                                isScrollControlled: true,
                                useSafeArea: true,
                                builder: (_) => const PairingWizardSheet(),
                              );
                            },
                    );
                  })
                ],
              ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.sync),
        label: const Text('Scan'),
        onPressed: () async {
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
