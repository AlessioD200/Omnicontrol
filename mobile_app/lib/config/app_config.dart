import 'package:shared_preferences/shared_preferences.dart';

/// Centralised hub configuration utilities.
class AppConfig {
  AppConfig._();

  static const _hubKey = 'hub_base_url';
  static const _linkedTokenKey = 'linked_account_token';
  static const fallbackHubUrl = String.fromEnvironment('OMNICONTROL_DEFAULT_HUB', defaultValue: '');

  static Future<String?> loadHubUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_hubKey) ?? (fallbackHubUrl.isNotEmpty ? fallbackHubUrl : null);
  }

  static Future<void> saveHubUrl(String? url) async {
    final prefs = await SharedPreferences.getInstance();
    if (url == null || url.isEmpty) {
      await prefs.remove(_hubKey);
    } else {
      await prefs.setString(_hubKey, url);
    }
  }

  static Future<void> saveLinkedToken(String? token) async {
    final prefs = await SharedPreferences.getInstance();
    if (token == null || token.isEmpty) {
      await prefs.remove(_linkedTokenKey);
    } else {
      await prefs.setString(_linkedTokenKey, token);
    }
  }

  static Future<String?> loadLinkedToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_linkedTokenKey);
  }
}
