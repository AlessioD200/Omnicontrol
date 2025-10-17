import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/omni_provider.dart';

class SamsungPairingPage extends StatefulWidget {
  final String deviceId;
  final String initialIp;
  final String initialName;
  const SamsungPairingPage({super.key, required this.deviceId, this.initialIp = '', this.initialName = ''});

  @override
  State<SamsungPairingPage> createState() => _SamsungPairingPageState();
}

class _SamsungPairingPageState extends State<SamsungPairingPage> {
  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _pinController = TextEditingController();
  String _status = 'idle';
  Timer? _pollTimer;
  Map<String, dynamic>? _lastResponse;
  Map<String, dynamic>? _deviceMeta;
  String? _controlTestResult;

  @override
  void initState() {
    super.initState();
    _ipController.text = widget.initialIp;
    _nameController.text = widget.initialName;
  }

  @override
  void dispose() {
    _ipController.dispose();
    _nameController.dispose();
    _pinController.dispose();
    _pollTimer?.cancel();
    super.dispose();
  }

  void _startPolling(String jobId) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 1), (_) async {
      try {
        final prov = Provider.of<OmniProvider>(context, listen: false);
        final status = await prov.api.getPairJobStatus(jobId);
        final st = status['status'] as String? ?? 'pending';
        setState(() {
          _status = st;
        });
        if (st == 'success' || st == 'failed') {
          _pollTimer?.cancel();
          // refresh provider to pick up any metadata changes
          await prov.refresh();
          // capture device metadata for display
          final foundList = prov.devices.where((d) => d.id == widget.deviceId).toList();
          if (foundList.isNotEmpty) {
            final found = foundList.first;
            setState(() {
              _deviceMeta = found.metadata ?? {};
            });
            // Try sending a quick test command to verify control
            try {
              await prov.remote(widget.deviceId, 'menu');
              setState(() {
                _controlTestResult = 'Test command sent: OK';
              });
            } catch (e) {
              setState(() {
                _controlTestResult = 'Test command failed: $e';
              });
            }
          }
        }
      } catch (_) {}
    });
  }

  Future<void> _pair() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    final ip = _ipController.text.trim();
    final name = _nameController.text.trim();
    if (ip.isEmpty) {
      setState(() {
        _status = 'missing_ip';
      });
      return;
    }
    setState(() {
      _status = 'starting';
    });

    try {
      // persist IP immediately
      await prov.api.postDeviceMetadata(widget.deviceId, {'samsung_ip': ip, 'samsung_remote_name': name});
      // Attempt direct pairing endpoint (supports passing PIN if provided)
      final body = {'ip': ip, 'name': name};
      if (_pinController.text.trim().isNotEmpty) body['pin'] = _pinController.text.trim();
      final resp = await prov.api.sendPairSamsung(widget.deviceId, body);
      _lastResponse = resp;
      // If backend started a job instead of immediate result, handle it
      if (resp.containsKey('job_id')) {
        final jobId = resp['job_id'] as String;
        setState(() {
          _status = 'job_started';
        });
        _startPolling(jobId);
      } else {
        setState(() {
          _status = resp['error'] != null ? 'failed' : 'success';
        });
        // refresh provider to pick up metadata changes
        await prov.refresh();
        final foundList = prov.devices.where((d) => d.id == widget.deviceId).toList();
        if (foundList.isNotEmpty) {
          final found = foundList.first;
          setState(() {
            _deviceMeta = found.metadata ?? {};
          });
          // Try sending a quick test command to verify control
          try {
            await prov.remote(widget.deviceId, 'menu');
            setState(() {
              _controlTestResult = 'Test command sent: OK';
            });
          } catch (e) {
            setState(() {
              _controlTestResult = 'Test command failed: $e';
            });
          }
        }
      }
    } catch (e) {
      setState(() {
        _status = 'error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Pair Samsung SmartView')),
      body: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(children: [
          TextField(controller: _ipController, decoration: const InputDecoration(labelText: 'TV IP / Host')),
          const SizedBox(height: 8),
          TextField(controller: _nameController, decoration: const InputDecoration(labelText: 'Remote name (optional)')),
          const SizedBox(height: 8),
          TextField(controller: _pinController, decoration: const InputDecoration(labelText: 'PIN (if TV shows it)'), keyboardType: TextInputType.number),
          const SizedBox(height: 12),
          Row(children: [
            ElevatedButton(onPressed: _pair, child: const Text('Start pairing')),
            const SizedBox(width: 12),
            ElevatedButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
          ]),
          const SizedBox(height: 20),
          Text('Status: $_status'),
          const SizedBox(height: 8),
          if (_lastResponse != null) ...[
            const Text('Response:'),
            SelectableText(const JsonEncoder.withIndent('  ').convert(_lastResponse), style: const TextStyle(fontFamily: 'monospace')),
            const SizedBox(height: 8),
          ],
          if (_deviceMeta != null) ...[
            const Text('Device metadata (saved):'),
            SelectableText(const JsonEncoder.withIndent('  ').convert(_deviceMeta), style: const TextStyle(fontFamily: 'monospace')),
            const SizedBox(height: 8),
          ],
          if (_controlTestResult != null) ...[
            const Text('Control test:'),
            SelectableText(_controlTestResult ?? '', style: const TextStyle(fontFamily: 'monospace')),
            const SizedBox(height: 8),
          ],
        ]),
      ),
    );
  }
}
