import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/omni_provider.dart';
import '../pairing/pairing_wizard.dart';

class OnboardingFlow extends StatefulWidget {
  const OnboardingFlow({super.key});

  @override
  State<OnboardingFlow> createState() => _OnboardingFlowState();
}

class _OnboardingFlowState extends State<OnboardingFlow> {
  int _step = 0;
  final TextEditingController _hubController = TextEditingController();
  final TextEditingController _tokenController = TextEditingController();
  List<String> _discoveredHubs = const [];
  bool _discovering = false;
  bool _connecting = false;

  @override
  void initState() {
    super.initState();
    final prov = Provider.of<OmniProvider>(context, listen: false);
    _hubController.text = prov.currentHub ?? '';
    _tokenController.text = prov.linkedAccount ?? '';
  }

  Future<void> _discover() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    setState(() {
      _discovering = true;
    });
    try {
      final hubs = await prov.discoverHubs();
      setState(() {
        _discoveredHubs = hubs;
      });
    } finally {
      setState(() {
        _discovering = false;
      });
    }
  }

  Future<void> _connectHub() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    final url = _hubController.text.trim();
    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please enter or select a hub URL')));
      return;
    }
    setState(() {
      _connecting = true;
    });
    try {
      await prov.configureHub(url);
      if (prov.connected) {
        setState(() => _step = 1);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Unable to connect to hub')));
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed to connect: $e')));
    } finally {
      setState(() {
        _connecting = false;
      });
    }
  }

  Future<void> _linkAccount() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    final token = _tokenController.text.trim();
    if (token.isEmpty) {
      setState(() => _step = 2);
      return;
    }
    try {
      await prov.linkAccountToken(token);
      setState(() => _step = 2);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Link failed: $e')));
    }
  }

  void _openPairingWizard() {
    showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => const PairingWizardSheet(),
    ).then((_) {
      Provider.of<OmniProvider>(context, listen: false).refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Welcome to Omnicontrol'),
      ),
      body: Stepper(
        currentStep: _step,
        controlsBuilder: (_, details) {
          return const SizedBox.shrink();
        },
        steps: [
          Step(
            isActive: _step == 0,
            title: const Text('Connect your hub'),
            subtitle: const Text('Detect your Raspberry Pi hub and verify connectivity'),
            content: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _hubController,
                  decoration: const InputDecoration(labelText: 'Hub URL', hintText: 'http://192.168.x.x:8000'),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: _discovering ? null : _discover,
                      icon: const Icon(Icons.search),
                      label: Text(_discovering ? 'Discovering…' : 'Discover on network'),
                    ),
                    FilledButton(
                      onPressed: _connecting ? null : _connectHub,
                      child: Text(_connecting ? 'Connecting…' : 'Connect'),
                    ),
                  ],
                ),
                if (_discoveredHubs.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  const Text('Found hubs:'),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: _discoveredHubs
                        .map((hub) => ActionChip(
                              label: Text(hub),
                              onPressed: () {
                                _hubController.text = hub;
                                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Hub selected: $hub')));
                              },
                            ))
                        .toList(),
                  )
                ],
              ],
            ),
          ),
          Step(
            isActive: _step == 1,
            title: const Text('Link your account'),
            subtitle: const Text('Optional — unlock remote access across devices'),
            content: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Enter the token provided by the mobile app or portal. Leave empty to skip.'),
                const SizedBox(height: 12),
                TextField(
                  controller: _tokenController,
                  decoration: const InputDecoration(labelText: 'Access token'),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _linkAccount,
                  child: const Text('Continue'),
                ),
                TextButton(
                  onPressed: () => setState(() => _step = 2),
                  child: const Text('Skip for now'),
                ),
              ],
            ),
          ),
          Step(
            isActive: _step == 2,
            title: const Text('Pair your first device'),
            subtitle: const Text('Set up TVs, boxes, speakers or cameras'),
            content: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Launch the guided wizard to pair Bluetooth devices or register IP cameras. You can add more later from the Devices tab.'),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _openPairingWizard,
                  icon: const Icon(Icons.playlist_add),
                  label: const Text('Open pairing wizard'),
                ),
                TextButton(
                  onPressed: () => Navigator.of(context).maybePop(),
                  child: const Text('Finish'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
