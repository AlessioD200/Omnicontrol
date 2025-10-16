import 'package:flutter/material.dart';
import '../models/device.dart';

class DeviceCard extends StatelessWidget {
  final OmnicontrolDevice device;
  final VoidCallback onTap;
  final VoidCallback? onPrimaryAction;
  final String? primaryActionLabel;

  const DeviceCard({super.key, required this.device, required this.onTap, this.onPrimaryAction, this.primaryActionLabel});

  IconData _iconForDevice() {
    final meta = device.metadata ?? {};
    final type = (meta['type'] ?? meta['category'] ?? '').toString().toLowerCase();
    if (type.contains('camera')) return Icons.videocam_outlined;
    if (type.contains('tv') || type.contains('monitor')) return Icons.tv_outlined;
    if (type.contains('speaker') || type.contains('audio')) return Icons.speaker_outlined;
    if (type.contains('box')) return Icons.important_devices_outlined;
    if (device.id.startsWith('tapo-')) return Icons.videocam_outlined;
    if (device.address.contains(':')) return Icons.bluetooth;
    return Icons.devices_other_outlined;
  }

  String get _subtitle {
    final meta = device.metadata ?? {};
    if (meta.containsKey('room') && (meta['room'] as String).isNotEmpty) {
      return meta['room'] as String;
    }
    if (device.address.isNotEmpty) return device.address;
    return 'ID: ${device.id}';
  }

  List<Widget> _buildBadges(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final badges = <Widget>[];
    if (device.paired) {
      badges.add(_StatusChip(label: 'Paired', icon: Icons.verified, color: colorScheme.secondary));
    }
    if (device.rssi != null) {
      final rssi = device.rssi!;
      final strength = rssi >= -60 ? 'Strong signal' : rssi >= -75 ? 'OK signal' : 'Weak signal';
      badges.add(_StatusChip(label: strength, icon: Icons.wifi_tethering, color: colorScheme.tertiary));
    }
    final meta = device.metadata ?? {};
    if (meta.containsKey('rtsp_url')) {
      badges.add(_StatusChip(label: 'Camera', icon: Icons.videocam, color: colorScheme.primary));
    }
    return badges;
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.primaryContainer,
                      shape: BoxShape.circle,
                    ),
                    padding: const EdgeInsets.all(10),
                    child: Icon(_iconForDevice(), color: Theme.of(context).colorScheme.onPrimaryContainer, size: 26),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          device.name.isEmpty ? 'Unnamed device' : device.name,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 4),
                        Text(_subtitle, style: Theme.of(context).textTheme.bodySmall),
                        if (_buildBadges(context).isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Wrap(spacing: 6, runSpacing: 6, children: _buildBadges(context)),
                        ],
                      ],
                    ),
                  ),
                  if (onPrimaryAction != null)
                    TextButton(onPressed: onPrimaryAction, child: Text(primaryActionLabel ?? 'Pair')),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Device ID: ${device.id}', style: Theme.of(context).textTheme.bodySmall),
                  const Icon(Icons.chevron_right),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;

  const _StatusChip({required this.label, required this.icon, required this.color});

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 16, color: color.computeLuminance() > 0.5 ? Colors.black : Colors.white),
      label: Text(label),
      backgroundColor: color.withOpacity(0.18),
      labelStyle: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    );
  }
}
