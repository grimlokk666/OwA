/**
 * Sovereign Overwatch — tactical dashboard shell
 * Map shell plus local feeds. Tiles come from the nav profile, not public OSM.
 */

(function () {
  const map = L.map('map', { zoomControl: false }).setView([40.0, -83.0], 7);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  window.SovereignMap = map;

  const deviceMarkers = L.layerGroup().addTo(map);

  function apiHeaders() {
    const headers = { Accept: 'application/json' };
    const token = (localStorage.getItem('sovereign.apiToken') || '').trim();
    if (token) headers['X-Overwatch-Token'] = token;
    return headers;
  }

  async function refreshAdsb() {
    const el = document.getElementById('adsb-feed');
    if (!el) return;
    try {
      const res = await fetch('/api/adsb', { headers: apiHeaders() });
      if (res.status === 401) {
        el.innerHTML =
          '<p class="text-amber-500">&gt; Unauthorized — set the API token in the node panel</p>';
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      if (data.configured === false || data.status === 'no receiver configured') {
        el.innerHTML = '<p class="text-zinc-500">&gt; no receiver configured</p>';
        return;
      }
      const aircraft = data.aircraft || [];
      if (!aircraft.length) {
        el.innerHTML =
          '<p class="text-zinc-500">&gt; receiver offline — no contacts</p>';
        return;
      }
      el.innerHTML = aircraft
        .slice(0, 12)
        .map((a) => {
          const hex = a.hex || a.icao || '?';
          const flight = a.flight || a.callsign || '————';
          const alt = a.alt_baro ?? a.altitude ?? '—';
          return `<div class="flex justify-between gap-2"><span>${flight.trim()}</span><span class="text-zinc-500">${hex}</span><span>${alt} ft</span></div>`;
        })
        .join('');
    } catch {
      el.innerHTML = '<p class="text-zinc-500">&gt; ADS-B unavailable</p>';
    }
  }

  async function refreshTelemetryTracks() {
    try {
      const res = await fetch('/api/telemetry/latest?limit=40', { headers: apiHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      deviceMarkers.clearLayers();
      for (const p of data.points || []) {
        if (!p.lat && !p.lon) continue;
        const marker = L.circleMarker([p.lat, p.lon], {
          radius: 6,
          color: '#34d399',
          fillColor: '#059669',
          fillOpacity: 0.85,
          weight: 1,
        });
        marker.bindPopup(
          `<strong>${p.callsign || p.deviceId}</strong><br/>${p.ts}<br/>bat ${p.battery ?? '—'}%`
        );
        deviceMarkers.addLayer(marker);
      }
    } catch {
      /* mesh may be down — map stays usable */
    }
  }

  async function refreshScanner() {
    const el = document.getElementById('scanner-status');
    if (!el) return;
    try {
      const res = await fetch('/api/scanner', { headers: apiHeaders() });
      if (res.status === 401) {
        el.textContent = 'UNAUTHORIZED';
        el.className = 'text-amber-400 font-bold';
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      el.textContent = data.status || 'UNKNOWN';
      el.className =
        data.status === 'ONLINE'
          ? 'text-emerald-400 font-bold'
          : 'text-amber-400 font-bold';
    } catch {
      el.textContent = 'OFFLINE';
      el.className = 'text-red-400 font-bold';
    }
  }

  // Wire mobile telemetry node UI if script loaded
  const callsignInput = document.getElementById('node-callsign');
  const tokenInput = document.getElementById('node-token');
  const keyInput = document.getElementById('node-key');
  const toggleBtn = document.getElementById('btn-telemetry-toggle');
  if (tokenInput) {
    tokenInput.value = localStorage.getItem('sovereign.apiToken') || '';
    tokenInput.addEventListener('change', () => {
      localStorage.setItem('sovereign.apiToken', tokenInput.value.trim());
      refreshAdsb();
      refreshScanner();
      refreshTelemetryTracks();
      if (window.SovereignNav) window.SovereignNav.onToken();
    });
  }
  if (keyInput) {
    keyInput.value = localStorage.getItem('sovereign.telemetryKey') || '';
    keyInput.addEventListener('change', () => {
      localStorage.setItem('sovereign.telemetryKey', keyInput.value.trim());
    });
  }
  if (window.SovereignTelemetry && callsignInput && toggleBtn) {
    const saved = localStorage.getItem('sovereign.callsign') || 'ALPHA-1';
    callsignInput.value = saved;
    callsignInput.addEventListener('change', () => {
      localStorage.setItem('sovereign.callsign', callsignInput.value.trim() || 'ALPHA-1');
      window.SovereignTelemetry.setCallsign(callsignInput.value.trim() || 'ALPHA-1');
    });

    toggleBtn.addEventListener('click', async () => {
      const running = window.SovereignTelemetry.isRunning();
      if (running) {
        await window.SovereignTelemetry.stop();
        toggleBtn.textContent = 'Arm Node';
      } else {
        window.SovereignTelemetry.setCallsign(callsignInput.value.trim() || 'ALPHA-1');
        await window.SovereignTelemetry.start();
        toggleBtn.textContent = 'Disarm';
      }
    });

    window.SovereignTelemetry.onStatus((status) => {
      const state = document.getElementById('node-state');
      const last = document.getElementById('node-last-fix');
      const queue = document.getElementById('node-queue');
      const badge = document.getElementById('telemetry-badge');
      if (state) state.textContent = status.state;
      if (last) last.textContent = status.lastFix || '—';
      if (queue) queue.textContent = String(status.queueDepth ?? 0);
      if (badge) {
        badge.classList.remove('hidden');
        badge.textContent = `NODE: ${status.state.toUpperCase()}`;
        badge.className =
          status.state === 'tracking'
            ? 'hidden sm:inline text-emerald-400'
            : 'hidden sm:inline text-amber-400';
      }
    });
  }

  refreshAdsb();
  refreshScanner();
  refreshTelemetryTracks();
  setInterval(refreshAdsb, 15_000);
  setInterval(refreshScanner, 30_000);
  setInterval(refreshTelemetryTracks, 20_000);

})();
