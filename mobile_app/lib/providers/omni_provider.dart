import 'package:flutter/material.dart';
import '../api/api_client.dart';
import '../config/app_config.dart';
import '../data/samsung_keys.dart';
import '../models/device.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OmniProvider extends ChangeNotifier {
  final ApiClient api;
  List<OmnicontrolDevice> devices = [];
  bool loading = false;
  bool connected = false;
  Map<String, dynamic>? hubInfo;
  String? linkedAccount;
  String? selectedHub;
  String? lastError;
  bool hideNoisyDevices = true;
  Map<String, String> pairingJobs = {}; // jobId -> status
  Future<void>? _initFuture;

  OmniProvider({required this.api});

  String? get currentHub => api.hasBaseUrl ? api.baseUrl : selectedHub;
  bool get hasHubConfigured => api.hasBaseUrl;

  Future<void> init() async {
    _initFuture ??= _initialize();
    return _initFuture!;
  }

  Future<void> _initialize() async {
    final prefs = await SharedPreferences.getInstance();
    hideNoisyDevices = prefs.getBool('hide_noisy_devices') ?? true;
    linkedAccount = await AppConfig.loadLinkedToken();
    final saved = await AppConfig.loadHubUrl();
    if (saved != null && saved.isNotEmpty) {
      api.setBaseUrl(saved);
      selectedHub = saved;
      await checkConnection();
      if (connected) {
        await refresh();
      }
    }
  }

  Future<void> refresh() async {
    if (!hasHubConfigured) {
      devices = [];
      notifyListeners();
      return;
    }
    loading = true;
    notifyListeners();
    try {
      final raw = await api.fetchDevices();

      // Dedupe devices by address when possible, otherwise by id.
      final Map<String, OmnicontrolDevice> byKey = {};
      String keyFor(OmnicontrolDevice d) {
        final aAddr = d.address.trim();
        if (aAddr.isNotEmpty) return aAddr.toUpperCase();
        return d.id;
      }

      OmnicontrolDevice chooseBetter(OmnicontrolDevice a, OmnicontrolDevice b) {
        // Prefer paired devices
        if (a.paired && !b.paired) return a;
        if (b.paired && !a.paired) return b;
        // Prefer one that has a proper name (not equal to address and non-empty)
        final aHasName = a.name.trim().isNotEmpty && a.name.trim() != a.address;
        final bHasName = b.name.trim().isNotEmpty && b.name.trim() != b.address;
        if (aHasName && !bHasName) return a;
        if (bHasName && !aHasName) return b;
        // Prefer one with RSSI (recent scan)
        if ((a.rssi ?? -999) > (b.rssi ?? -999)) return a;
        return a;
      }

      for (final d in raw) {
        final k = keyFor(d);
        if (byKey.containsKey(k)) {
          byKey[k] = chooseBetter(byKey[k]!, d);
        } else {
          byKey[k] = d;
        }
      }

      // Filter out noisy unnamed MAC-only devices: if a device has no useful name
      // (name empty or equal to address), is not paired and has no RSSI (not recently scanned),
      // hide it to reduce noise.
      devices = byKey.values.where((d) {
        final hasName = d.name.trim().isNotEmpty && d.name.trim() != d.address;
        if (hasName) return true;
        if (d.paired) return true;
        if (d.rssi != null) return true;
        return false;
      }).toList();

      // Sort: paired first, then by name/address
      devices.sort((a, b) {
        if (a.paired && !b.paired) return -1;
        if (b.paired && !a.paired) return 1;
        return a.name.toLowerCase().compareTo(b.name.toLowerCase());
      });
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> scan() async {
    if (!hasHubConfigured) {
      lastError = 'Configure a hub before scanning';
      notifyListeners();
      throw Exception(lastError);
    }
    lastError = null;
    try {
      await api.scan();
      await refresh();
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// Start a pairing job and poll its status in the background.
  /// Returns the jobId immediately so callers can observe progress via
  /// [pairingJobs] and/or await [waitForPairingJob].
  Future<String> startPairingAndWatch(Map<String, dynamic> payload, {int timeoutSeconds = 60}) async {
    lastError = null;
    final jobId = await api.pair(payload);
    pairingJobs[jobId] = 'pending';
    notifyListeners();

    // Spawn background poller (do not await here so UI can show progress)
    Future(() async {
      final deadline = DateTime.now().add(Duration(seconds: timeoutSeconds));
      int delaySec = 1;
      try {
        while (DateTime.now().isBefore(deadline)) {
          try {
            final status = await api.getPairJobStatus(jobId);
            final st = status['status'] as String? ?? 'pending';
            pairingJobs[jobId] = st;
            notifyListeners();
            if (st == 'success') {
              // refresh devices to pick up paired state
              await refresh();
              break;
            }
            if (st == 'failed') {
              // record error if provided
              final err = status['error'];
              if (err != null) lastError = err.toString();
              break;
            }
          } catch (_) {
            // ignore transient errors
          }
          await Future.delayed(Duration(seconds: delaySec));
          // exponential backoff with ceiling
          delaySec = (delaySec * 2).clamp(1, 8);
        }
      } catch (e) {
        lastError = e.toString();
      } finally {
        // schedule removal of finished job after TTL so UI doesn't accumulate
        Future.delayed(const Duration(seconds: 30), () {
          pairingJobs.remove(jobId);
          notifyListeners();
        });
      }
    });

    return jobId;
  }

  /// Wait for a pairing job to reach a terminal state ('success' or 'failed').
  /// Returns the final status string or throws on timeout.
  Future<String> waitForPairingJob(String jobId, {int timeoutSeconds = 60}) async {
    final deadline = DateTime.now().add(Duration(seconds: timeoutSeconds));
    while (DateTime.now().isBefore(deadline)) {
      final st = pairingJobs[jobId];
      if (st != null && (st == 'success' || st == 'failed')) return st;
      await Future.delayed(const Duration(milliseconds: 500));
    }
    throw Exception('Timeout waiting for pairing job $jobId');
  }

  Future<void> checkConnection() async {
    lastError = null;
    try {
      final h = await api.health();
      hubInfo = h;
      // require a simple status: ok marker to mark connected
      if (h['status'] == 'ok') {
        connected = true;
      } else {
        connected = false;
        lastError = 'Unexpected health response';
      }
    } catch (e) {
      connected = false;
      hubInfo = null;
      lastError = e.toString();
    }
    notifyListeners();
  }

  Future<void> linkHub(String hubUrl, String token) async {
    lastError = null;
    try {
      // Call server to link account (backend may validate token)
      await api.linkHubToAccount(hubUrl, token);
      linkedAccount = token;
      selectedHub = hubUrl;
      api.setBaseUrl(hubUrl);
      await AppConfig.saveHubUrl(hubUrl);
      await AppConfig.saveLinkedToken(token);
      // Optionally request server-confirmed info
      await checkConnection();
      notifyListeners();
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> configureHub(String hubUrl) async {
    selectedHub = hubUrl;
    api.setBaseUrl(hubUrl);
    await AppConfig.saveHubUrl(hubUrl);
    await checkConnection();
    if (connected) {
      await refresh();
    }
  }

  Future<void> linkAccountToken(String token) async {
    final hubUrl = currentHub;
    if (hubUrl == null) {
      throw Exception('Configure hub before linking account');
    }
    await api.linkHubToAccount(hubUrl, token);
    linkedAccount = token;
    await AppConfig.saveLinkedToken(token);
    notifyListeners();
  }

  Future<void> clearHub() async {
    selectedHub = null;
    devices = [];
    api.clearBaseUrl();
    await AppConfig.saveHubUrl(null);
    connected = false;
    notifyListeners();
  }

  Future<Map<String, dynamic>> checkFirmware() async {
    try {
      final res = await api.checkFirmware();
      return res;
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<List<String>> discoverHubs() async {
    return await api.discoverHubs();
  }

  void connectTo(String baseUrl) {
    api.setBaseUrl(baseUrl);
    SharedPreferences.getInstance().then((prefs) => prefs.setString('hub_base_url', baseUrl));
    // await check and report via provider state
    checkConnection();
  }

  Future<void> toggle(String id) async {
    lastError = null;
    try {
      await api.toggle(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> ping(String id) async {
    lastError = null;
    try {
      await api.ping(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  // Media controls
  Future<void> play(String id) async {
    lastError = null;
    try {
      await api.play(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> pause(String id) async {
    lastError = null;
    try {
      await api.pause(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> next(String id) async {
    lastError = null;
    try {
      await api.next(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> previous(String id) async {
    lastError = null;
    try {
      await api.previous(id);
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> remote(String id, String action) async {
    lastError = null;
    try {
      // If the device supports Samsung SmartView (protocol or metadata), prefer inline Samsung payload
      final dev = devices.firstWhere((d) => d.id == id, orElse: () => throw Exception('Unknown device'));
      final supportsSamsung = dev.protocols.contains('samsung') || dev.protocols.contains('smartview') ||
          (dev.metadata != null && (
            dev.metadata!.containsKey('samsung_commands') ||
            dev.metadata!.containsKey('smartview_token') ||
            dev.metadata!.containsKey('samsung_token') ||
            dev.metadata!.containsKey('samsung_client_id') ||
            dev.metadata!.containsKey('samsung_ip')
          ));
      if (supportsSamsung) {
        // Map logical action to SmartView key if available
        final key = samsungKeyMap[action] ?? action.toUpperCase();
        final payload = {
          'command': {
            'transport': 'samsung',
            'key': key,
            'cmd': 'Click',
          }
        };
        await api.sendInlineCommand(id, payload);
        return;
      }
      await api.sendCommand(id, {"command": action});
    } catch (e) {
      // Try to connect the device and retry once
      try {
        final connected = await api.connectDevice(id);
        if (connected) {
          final dev = devices.firstWhere((d) => d.id == id, orElse: () => throw Exception('Unknown device'));
          final supportsSamsung = dev.protocols.contains('samsung') || dev.protocols.contains('smartview') || (dev.metadata != null && (dev.metadata!.containsKey('samsung_commands') || dev.metadata!.containsKey('smartview_token')));
          if (supportsSamsung) {
            final payload = {'command': {'transport': 'samsung', 'key': action.toUpperCase(), 'cmd': 'Click'}};
            await api.sendInlineCommand(id, payload);
            return;
          }
          await api.sendCommand(id, {"command": action});
          return;
        }
      } catch (_) {
        // ignore connect errors, fall through to rethrow
      }
      lastError = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> registerCamera({
    required String id,
    required String name,
    required String ip,
    required String username,
    required String password,
    String path = 'stream1',
  }) async {
    await api.registerCamera(
      id: id,
      name: name,
      ip: ip,
      username: username,
      password: password,
      path: path,
    );
    await refresh();
  }
}
