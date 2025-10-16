import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'pages/dashboard_page.dart';
import 'pages/devices_page.dart';
import 'pages/login_page.dart';
import 'pages/onboarding/onboarding_flow.dart';
import 'pages/settings_page.dart';
import 'providers/omni_provider.dart';
import 'theme/app_theme.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) {
        final provider = OmniProvider(api: ApiClient());
        provider.init();
        return provider;
      },
      child: Consumer<OmniProvider>(
        builder: (context, prov, _) {
          final showOnboarding = !prov.hasHubConfigured || !prov.connected;
          return MaterialApp(
            title: 'Omnicontrol',
            theme: AppTheme.light(),
            darkTheme: AppTheme.dark(),
            themeMode: ThemeMode.system,
            routes: {
              '/login': (_) => const LoginPage(),
            },
            home: showOnboarding ? const OnboardingFlow() : const RootPage(),
          );
        },
      ),
    );
  }
}

class RootPage extends StatefulWidget {
  const RootPage({super.key});

  @override
  State<RootPage> createState() => _RootPageState();
}

class _RootPageState extends State<RootPage> {
  int _index = 1;

  static const List<Widget> _pages = [
    DashboardPage(),
    DevicesPage(),
    SettingsPage(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.devices_other_outlined), selectedIcon: Icon(Icons.devices), label: 'Devices'),
          NavigationDestination(icon: Icon(Icons.settings_outlined), selectedIcon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }
}
