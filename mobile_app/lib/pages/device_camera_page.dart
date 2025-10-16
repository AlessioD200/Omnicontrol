import 'package:flutter/material.dart';
import 'package:flutter_vlc_player/flutter_vlc_player.dart';
import 'package:provider/provider.dart';
import '../providers/omni_provider.dart';

class DeviceCameraPage extends StatefulWidget {
  final String deviceId;
  final String? initialRtsp;
  const DeviceCameraPage({super.key, required this.deviceId, this.initialRtsp});

  @override
  State<DeviceCameraPage> createState() => _DeviceCameraPageState();
}

class _DeviceCameraPageState extends State<DeviceCameraPage> {
  VlcPlayerController? _vlcController;
  String? _rtsp;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _rtsp = widget.initialRtsp;
    WidgetsBinding.instance.addPostFrameCallback((_) => _initStream());
  }

  Future<void> _initStream() async {
    final prov = Provider.of<OmniProvider>(context, listen: false);
    try {
      if (_rtsp == null || _rtsp!.isEmpty) {
        final info = await prov.api.getStreamInfo(widget.deviceId);
        _rtsp = info['rtsp_url'] as String? ?? info['snapshot_url'] as String?;
      }
      if (_rtsp != null && _rtsp!.isNotEmpty && _rtsp!.startsWith('rtsp')) {
  _vlcController = VlcPlayerController.network(_rtsp!);
        await _vlcController!.initialize();
      }
    } catch (e) {
      // ignore; will fall back to snapshot usage
    }
    setState(() {
      _loading = false;
    });
  }

  @override
  void dispose() {
    _vlcController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Live Camera')),
      body: Center(
        child: _loading
            ? const CircularProgressIndicator()
            : _vlcController != null
                ? VlcPlayer(controller: _vlcController!, aspectRatio: 16 / 9)
                : _rtsp != null
                    ? Image.network(_rtsp!, errorBuilder: (c, e, s) => Center(child: Text('Failed to load camera: $e')))
                    : const Text('No stream available'),
      ),
    );
  }
}
