import type { CapacitorConfig } from '@capacitor/cli';

/**
 * Sovereign Overwatch — Capacitor native wrapper
 *
 * Local-first: the WebView loads your self-hosted dashboard over Tailscale.
 * No Play Store / App Store distribution required — sideload the APK/IPA.
 *
 * Set SOVEREIGN_DASHBOARD_URL to your Tailscale MagicDNS or mesh IP, e.g.:
 *   https://overwatch.tailnet-name.ts.net
 * or leave empty to serve the bundled PWA shell (www/) which then navigates
 * to the URL configured in local settings.
 */
const dashboardUrl = process.env.SOVEREIGN_DASHBOARD_URL?.trim() || undefined;

const config: CapacitorConfig = {
  appId: 'd.sovereign.overwatch',
  appName: 'Sovereign Overwatch',
  webDir: 'mobile/dist',
  // When set, Capacitor loads the remote tactical dashboard directly.
  // Telemetry still runs from the bundled JS injected via the shell.
  server: dashboardUrl
    ? {
        url: dashboardUrl,
        cleartext: dashboardUrl.startsWith('http://'),
        allowNavigation: [
          '*.ts.net',
          '100.*',
          '10.*',
          '172.16.*',
          '192.168.*',
          'localhost',
          '127.0.0.1',
        ],
      }
    : {
        // Bundled PWA; operator configures backend URL in-app.
        androidScheme: 'https',
        iosScheme: 'https',
        cleartext: true,
        allowNavigation: [
          '*.ts.net',
          '100.*',
          '10.*',
          '172.16.*',
          '192.168.*',
          'localhost',
          '127.0.0.1',
        ],
      },
  android: {
    allowMixedContent: true,
    backgroundColor: '#0a0e14',
    webContentsDebuggingEnabled: false,
  },
  ios: {
    backgroundColor: '#0a0e14',
    contentInset: 'automatic',
    allowsLinkPreview: false,
    scrollEnabled: true,
  },
  plugins: {
    Geolocation: {
      // Request precise location for OwnTracks-style telemetry
    },
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: '#0a0e14',
    },
  },
};

export default config;
