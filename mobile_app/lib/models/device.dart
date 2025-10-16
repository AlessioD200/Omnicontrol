class OmnicontrolDevice {
  final String id;
  final String name;
  final String address;
  final int? rssi;
  final bool paired;
  final Map<String, dynamic>? metadata;

  OmnicontrolDevice({required this.id, required this.name, required this.address, this.rssi, this.paired = false, this.metadata});

  factory OmnicontrolDevice.fromJson(Map<String, dynamic> json) => OmnicontrolDevice(
        id: json['id'] as String,
        name: json['name'] as String,
        address: json['address'] as String,
        rssi: json['rssi'] != null ? (json['rssi'] as num).toInt() : null,
        paired: json['paired'] == true,
        metadata: json['metadata'] as Map<String, dynamic>?,
      );
}
