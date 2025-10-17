class OmnicontrolDevice {
  final String id;
  final String name;
  final String address;
  final int? rssi;
  final bool paired;
  final List<String> protocols;
  final Map<String, dynamic>? metadata;

  OmnicontrolDevice({
    required this.id,
    required this.name,
    required this.address,
    this.rssi,
    this.paired = false,
    this.protocols = const [],
    this.metadata,
  });

  factory OmnicontrolDevice.fromJson(Map<String, dynamic> json) {
    final prot = <String>[];
    if (json['protocols'] is List) {
      try {
        for (final e in (json['protocols'] as List)) {
          if (e is String && e.isNotEmpty) prot.add(e.toLowerCase());
        }
      } catch (_) {}
    }
    return OmnicontrolDevice(
      id: json['id'] as String,
      name: json['name'] as String,
      address: json['address'] as String,
      rssi: json['rssi'] != null ? (json['rssi'] as num).toInt() : null,
      paired: json['paired'] == true,
      protocols: prot,
      metadata: json['metadata'] as Map<String, dynamic>?,
    );
  }
}
