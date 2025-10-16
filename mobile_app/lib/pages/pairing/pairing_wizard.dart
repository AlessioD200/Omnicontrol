import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/omni_provider.dart';
import '../../models/device.dart';

enum PairingType { bluetooth, camera }

class PairingWizardSheet extends StatefulWidget {
  const PairingWizardSheet({super.key});

  @override
  State<PairingWizardSheet> createState() => _PairingWizardSheetState();
}

class _PairingWizardSheetState extends State<PairingWizardSheet> {
  PairingType? _type;
  OmnicontrolDevice? _selectedDevice;
  bool _submitting = false;
  String? _statusMessage;
  final _cameraIdController = TextEditingController();
  final _cameraNameController = TextEditingController();
  final _cameraIpController = TextEditingController();
  final _cameraUserController = TextEditingController();
  final _cameraPassController = TextEditingController();
  final _cameraPathController = TextEditingController(text: 'stream1');

  @override
  void initState() {
    super.initState();
    final prov = Provider.of<OmniProvider>(context, listen: false);
    prov.refresh();
  }

  Future<void> _startScan() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    try {
      await prov.scan();
      setState(() {
        _statusMessage = 'Scan complete';
      });
    } catch (e) {
      setState(() {
        _statusMessage = 'Scan failed: $e';
      });
    }
  }

  Future<void> _pairBluetooth() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    final device = _selectedDevice;
    if (device == null) {
      setState(() {
        _statusMessage = 'Select a device to pair';
      });
      return;
    }
    setState(() {
      _submitting = true;
      _statusMessage = 'Pairing ${device.name}…';
    });
    try {
      final jobId = await prov.startPairingAndWatch({
        'address': device.address,
        'name': device.name,
        'device_id': device.id,
      });
      final result = await prov.waitForPairingJob(jobId, timeoutSeconds: 120);
      if (!mounted) return;
      setState(() {
        _statusMessage = result == 'success' ? 'Paired successfully' : 'Pairing status: $result';
      });
      if (result == 'success') {
        Navigator.of(context).pop(true);
      }
    } catch (e) {
      setState(() {
        _statusMessage = 'Pairing failed: $e';
      });
    } finally {
      setState(() {
        _submitting = false;
      });
    }
  }

  Future<void> _registerCamera() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    final id = _cameraIdController.text.trim();
    final ip = _cameraIpController.text.trim();
    final username = _cameraUserController.text.trim();
    final password = _cameraPassController.text.trim();
    final path = _cameraPathController.text.trim().isEmpty ? 'stream1' : _cameraPathController.text.trim();
    if (id.isEmpty || ip.isEmpty || username.isEmpty || password.isEmpty) {
      setState(() {
        _statusMessage = 'Fill all required camera fields';
      });
      return;
    }
    setState(() {
      _submitting = true;
      _statusMessage = 'Registering camera…';
    });
    try {
      await prov.registerCamera(
        id: id,
        name: _cameraNameController.text.trim().isEmpty ? id : _cameraNameController.text.trim(),
        ip: ip,
        username: username,
        password: password,
        path: path,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      setState(() {
        _statusMessage = 'Registration failed: $e';
      });
    } finally {
      setState(() {
        _submitting = false;
      });
    }
  }

  Widget _buildBluetoothStep(OmniProvider prov) {
    final devices = prov.devices;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FilledButton.icon(
          onPressed: _submitting ? null : _startScan,
          icon: const Icon(Icons.sync),
          label: Text(_submitting ? 'Scanning…' : 'Scan for nearby devices'),
        ),
        const SizedBox(height: 16),
        if (devices.isEmpty)
          const Text('No devices discovered yet. Start a scan to populate the list.'),
        if (devices.isNotEmpty)
          SizedBox(
            height: 220,
            child: ListView.builder(
              itemCount: devices.length,
              itemBuilder: (context, index) {
                final d = devices[index];
                final selected = _selectedDevice?.id == d.id;
                return Card(
                  color: selected ? Theme.of(context).colorScheme.primaryContainer : null,
                  child: ListTile(
                    title: Text(d.name.isEmpty ? 'Unnamed device' : d.name),
                    subtitle: Text(d.address),
                    trailing: d.paired ? const Icon(Icons.verified, color: Colors.green) : null,
                    onTap: () => setState(() => _selectedDevice = d),
                  ),
                );
              },
            ),
          ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _submitting ? null : _pairBluetooth,
          child: Text(_submitting ? 'Pairing…' : 'Pair selected device'),
        ),
      ],
    );
  }

  Widget _buildCameraStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _cameraIdController,
          decoration: const InputDecoration(labelText: 'Device ID (e.g. living-room-cam)'),
        ),
        TextField(
          controller: _cameraNameController,
          decoration: const InputDecoration(labelText: 'Display name'),
        ),
        TextField(
          controller: _cameraIpController,
          decoration: const InputDecoration(labelText: 'IP address'),
          keyboardType: TextInputType.url,
        ),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _cameraUserController,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                controller: _cameraPassController,
                decoration: const InputDecoration(labelText: 'Password'),
                obscureText: true,
              ),
            ),
          ],
        ),
        TextField(
          controller: _cameraPathController,
          decoration: const InputDecoration(labelText: 'RTSP path', hintText: 'stream1'),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _submitting ? null : _registerCamera,
          child: Text(_submitting ? 'Registering…' : 'Register camera'),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      minChildSize: 0.6,
      builder: (context, scrollController) {
        return SingleChildScrollView(
          controller: scrollController,
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Pairing wizard', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                  IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close)),
                ],
              ),
              const SizedBox(height: 8),
              const Text('Choose the device type to begin. The wizard guides Bluetooth pairing or camera registration.'),
              const SizedBox(height: 16),
              SegmentedButton<PairingType>(
                segments: const [
                  ButtonSegment(value: PairingType.bluetooth, icon: Icon(Icons.bluetooth), label: Text('Bluetooth devices')),
                  ButtonSegment(value: PairingType.camera, icon: Icon(Icons.videocam), label: Text('IP cameras')),
                ],
                selected: _type == null ? <PairingType>{} : {_type!},
                onSelectionChanged: (value) {
                  setState(() {
                    _type = value.isEmpty ? null : value.single;
                  });
                },
              ),
              const SizedBox(height: 20),
              if (_type == PairingType.bluetooth) _buildBluetoothStep(prov),
              if (_type == PairingType.camera) _buildCameraStep(),
              if (_statusMessage != null) ...[
                const SizedBox(height: 16),
                Text(_statusMessage!, style: TextStyle(color: Theme.of(context).colorScheme.primary)),
              ],
            ],
          ),
        );
      },
    );
  }
}
