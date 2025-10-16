import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/device.dart';
import 'dart:io';
import 'package:multicast_dns/multicast_dns.dart';

class ApiClient {
  String baseUrl;
  ApiClient({required this.baseUrl});

  void setBaseUrl(String url) => baseUrl = url;

  Future<Map<String, dynamic>> health() async {
    final res = await http.get(Uri.parse('$baseUrl/api/health'));
    if (res.statusCode != 200) throw Exception('Health check failed: $res.statusCode');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<OmnicontrolDevice>> fetchDevices() async {
    final res = await http.get(Uri.parse('$baseUrl/api/devices'));
    if (res.statusCode != 200) throw Exception('Failed to load devices');
    final body = jsonDecode(res.body);
    List<dynamic> jsonList;
    if (body is List) {
      jsonList = body;
    } else if (body is Map && body.containsKey('devices') && body['devices'] is List) {
      jsonList = body['devices'] as List<dynamic>;
    } else {
      throw Exception('Unexpected devices response: ${res.body}');
    }
    return jsonList.map((j) => OmnicontrolDevice.fromJson(j as Map<String, dynamic>)).toList();
  }

  Future<void> scan() async {
    try {
      final res = await http.post(Uri.parse('$baseUrl/api/scan'));
        if (res.statusCode != 200) {
          final body = res.body;
          throw Exception('Scan failed: ${res.statusCode} $body');
        }
    } catch (e) {
      throw Exception('Scan request error: $e');
    }
  }

  /// Discover Omnicontrol hubs on the local network by probing common ports.
  Future<List<String>> discoverHubs({int timeoutMs = 400}) async {
    final results = <String>{};
    // 1) Try mDNS discovery for HTTP services
    try {
      final MDnsClient client = MDnsClient();
      await client.start();
      // browse for _http._tcp.local services
      await for (final PtrResourceRecord ptr in client.lookup<PtrResourceRecord>(ResourceRecordQuery.serverPointer('_http._tcp.local'))) {
        final String domain = ptr.domainName;
        // lookup SRV for port and target
        await for (final SrvResourceRecord srv in client.lookup<SrvResourceRecord>(ResourceRecordQuery.service(domain))) {
          final target = srv.target;
          final port = srv.port;
          // resolve A records for the target
          await for (final IPAddressResourceRecord ip in client.lookup<IPAddressResourceRecord>(ResourceRecordQuery.addressIPv4(target))) {
            final host = ip.address.address;
            final base = 'http://$host:$port';
            try {
              final resp = await http.get(Uri.parse('$base/api/health')).timeout(Duration(milliseconds: timeoutMs));
              if (resp.statusCode == 200) results.add(base);
            } catch (_) {}
          }
        }
      }
      client.stop();
    } catch (_) {
      // ignore mDNS errors — we'll fallback
    }

    if (results.isNotEmpty) return results.toList();

    // 2) Fallback: subnet probe similar to previous implementation
    try {
      final ifaces = await NetworkInterface.list(includeLoopback: false, type: InternetAddressType.IPv4);
      String? prefix;
      for (final iface in ifaces) {
        for (final addr in iface.addresses) {
          final ip = addr.address;
          if (ip.contains('.')) {
            final parts = ip.split('.');
            if (parts.length == 4) {
              prefix = '${parts[0]}.${parts[1]}.${parts[2]}';
              break;
            }
          }
        }
        if (prefix != null) break;
      }
      prefix ??= '192.168.1';

      final futures = <Future>[];
      for (int i = 1; i < 255; i++) {
        final host = '$prefix.$i';
        final uri = Uri.parse('http://$host:8000/api/health');
        futures.add(http.get(uri).timeout(Duration(milliseconds: timeoutMs)).then((resp) {
          if (resp.statusCode == 200) {
            results.add('http://$host:8000');
          }
        }).catchError((_) {}));
        if (futures.length >= 50) {
          await Future.wait(futures);
          futures.clear();
        }
      }
      if (futures.isNotEmpty) await Future.wait(futures);
    } catch (e) {
      // ignore discovery errors
    }
    return results.toList();
  }

  Future<void> toggle(String id) async {
    try {
      final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/toggle'));
      if (res.statusCode != 200) throw Exception('Toggle failed: ${res.statusCode} ${res.body}');
    } catch (e) {
      // rethrow with context for UI
      throw Exception('Toggle request error: $e');
    }
  }

  Future<void> ping(String id) async {
    try {
      final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/ping'));
      if (res.statusCode != 200) throw Exception('Ping failed: ${res.statusCode} ${res.body}');
    } catch (e) {
      throw Exception('Ping request error: $e');
    }
  }

  /// Start a pairing job on the hub and poll for completion.
  Future<String> pair(Map<String, dynamic> payload) async {
    final res = await http.post(Uri.parse('$baseUrl/api/pairings/jobs'), body: jsonEncode(payload), headers: {'Content-Type': 'application/json'});
    if (res.statusCode >= 400) throw Exception('Pairing job start failed: ${res.body}');
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final jobId = body['job_id'] as String?;
    if (jobId == null || jobId.isEmpty) throw Exception('Invalid job id from hub');
    return jobId;
  }

  Future<Map<String, dynamic>> getPairJobStatus(String jobId) async {
    final res = await http.get(Uri.parse('$baseUrl/api/pairings/jobs/$jobId'));
    if (res.statusCode != 200) throw Exception('Failed to get pairing job status: ${res.body}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<void> sendCommand(String id, Map<String, dynamic> body) async {
    final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/command'), body: jsonEncode(body), headers: {'Content-Type': 'application/json'});
    if (res.statusCode >= 400) throw Exception('Command failed: ${res.body}');
  }

  // Media control helpers (calls to backend media endpoints)
  Future<void> mediaAction(String id, String action) async {
    final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/media/$action'));
    if (res.statusCode >= 400) throw Exception('Media action failed: ${res.body}');
  }

  Future<void> play(String id) async => mediaAction(id, 'play');
  Future<void> pause(String id) async => mediaAction(id, 'pause');
  Future<void> next(String id) async => mediaAction(id, 'next');
  Future<void> previous(String id) async => mediaAction(id, 'previous');

  // Auth / account linking (placeholder endpoints)
  Future<void> linkHubToAccount(String hubUrl, String token) async {
    final res = await http.post(Uri.parse('$baseUrl/api/account/link'), body: jsonEncode({'hub': hubUrl, 'token': token}), headers: {'Content-Type': 'application/json'});
    if (res.statusCode >= 400) throw Exception('Link hub failed: ${res.body}');
  }

  // Firmware check
  Future<Map<String, dynamic>> checkFirmware() async {
    final res = await http.get(Uri.parse('$baseUrl/api/updates/latest'));
    if (res.statusCode != 200) throw Exception('Firmware check failed: ${res.body}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<bool> connectDevice(String id) async {
    try {
      final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/connect'));
      if (res.statusCode == 200) {
        final body = jsonDecode(res.body) as Map<String, dynamic>;
        return body['connected'] == true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  Future<void> postDeviceMetadata(String id, Map<String, dynamic> metadata) async {
    final res = await http.post(Uri.parse('$baseUrl/api/devices/$id/metadata'), body: jsonEncode(metadata), headers: {'Content-Type':'application/json'});
    if (res.statusCode >= 400) throw Exception('Failed to update metadata: ${res.body}');
  }

  Future<Map<String, dynamic>> getStreamInfo(String id) async {
    final res = await http.get(Uri.parse('$baseUrl/api/devices/$id/stream_info'));
    if (res.statusCode != 200) throw Exception('Failed to get stream info: ${res.body}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }
}
