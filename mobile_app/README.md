# Omnicontrol Mobile App

This Flutter app connects to the Omnicontrol backend running on your Raspberry Pi and provides the device scan/list/control UI on iOS and Android.

Run the app

1. Install Flutter and set up your platforms (Android/iOS) following https://flutter.dev/docs/get-started/install
2. Open the project folder:

```bash
cd mobile_app
flutter pub get
flutter run
```

Configure backend

Edit `lib/main.dart` and replace the placeholder IP `http://192.168.1.100:8000` with your Pi's IP address (the backend listens on port 8000 by default).

Notes

- The app uses simple REST calls to the existing Omnicontrol backend. Pairing and pairing-required flows are proxied by the backend; the app only displays results and posts pairing payloads.
- If you plan to ship this app, you should add a settings screen to persist the backend base URL and secure the API (authentication).
# mobile_app

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Lab: Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Cookbook: Useful Flutter samples](https://docs.flutter.dev/cookbook)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.
