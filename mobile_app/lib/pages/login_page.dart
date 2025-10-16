import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _hubController = TextEditingController();
  final _tokenController = TextEditingController();
  bool _loading = false;

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    return Scaffold(
      appBar: AppBar(title: const Text('Link hub to account')),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(children: [
          TextField(controller: _hubController, decoration: const InputDecoration(labelText: 'Hub base URL (http://host:8000)')),
          const SizedBox(height: 8),
          TextField(controller: _tokenController, decoration: const InputDecoration(labelText: 'Account token (or email)'), autocorrect: false),
          const SizedBox(height: 12),
          ElevatedButton(
            onPressed: _loading
                ? null
                : () async {
                    setState(() => _loading = true);
                    try {
                      await prov.linkHub(_hubController.text.trim(), _tokenController.text.trim());
                      if (!context.mounted) return;
                      Navigator.of(context).pop();
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Hub linked')));
                    } catch (e) {
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Link failed: $e')));
                    } finally {
                      setState(() => _loading = false);
                    }
                  },
            child: _loading ? const CircularProgressIndicator() : const Text('Link Hub'),
          ),
        ]),
      ),
    );
  }
}
