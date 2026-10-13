# Mobile companion (Capacitor)

TypeScript shell that:

1. Embeds the self-hosted Overwatch dashboard (Tailscale URL).
2. Runs a 60s GPS telemetry loop with IndexedDB offline queue.

Prefer editing `capacitor.config.ts` (authoritative). `capacitor.config.json` is
kept as a JSON twin for tooling that does not load TS configs.

See [../docs/MOBILE.md](../docs/MOBILE.md) for Android APK, HTTPS-only network
security, release keystore signing, and iOS steps.
