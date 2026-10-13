/**
 * Self-hosted search, routing, follow-me, and OHGO camera pins.
 * Tiles, geocode, and routes stay on this origin. No public OSM tile host.
 */
(function () {
  const REROUTE_METERS = 60;
  const REROUTE_HITS = 2;
  const REROUTE_COOLDOWN_MS = 15000;
  const SPEECH_COOLDOWN_MS = 2500;

  const map = window.SovereignMap;
  if (!map) return;

  const destinationLayer = L.layerGroup().addTo(map);
  const routeLayer = L.layerGroup().addTo(map);
  const cameraLayer = L.layerGroup().addTo(map);
  const gpsLayer = L.layerGroup().addTo(map);

  let destination = null;
  let routeCoords = [];
  let routeSteps = [];
  let stepIndex = -1;
  let gps = null;
  let gpsAt = 0;
  let watchId = null;
  let follow = false;
  let offRouteHits = 0;
  let lastRerouteAt = 0;
  let lastSpoken = '';
  let lastSpokenAt = 0;
  let searchTimer = 0;
  let tileWarned = false;
  let snapUrl = '';

  const searchInput = document.getElementById('nav-search');
  const resultsEl = document.getElementById('nav-results');
  const profileEl = document.getElementById('nav-profile');
  const followBtn = document.getElementById('btn-follow');
  const speechEl = document.getElementById('nav-speech');
  const banner = document.getElementById('nav-banner');
  const stepsEl = document.getElementById('route-steps');
  const tileStatus = document.getElementById('tile-status');
  const camContainer = document.getElementById('cam-container');
  const camList = document.getElementById('cam-list');

  function headers() {
    const value = { Accept: 'application/json' };
    const token = (localStorage.getItem('sovereign.apiToken') || '').trim();
    if (token) value['X-Overwatch-Token'] = token;
    return value;
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
    ));
  }

  function setBanner(text) {
    if (!banner) return;
    if (!text) {
      banner.hidden = true;
      banner.textContent = '';
      return;
    }
    banner.hidden = false;
    banner.textContent = text;
  }

  function profile() {
    return profileEl && profileEl.value ? profileEl.value : 'auto';
  }

  function speak(text, force) {
    if (!speechEl || !speechEl.checked || !text) return;
    if (!window.speechSynthesis || typeof SpeechSynthesisUtterance !== 'function') return;
    const now = Date.now();
    if (!force && text === lastSpoken && now - lastSpokenAt < SPEECH_COOLDOWN_MS) return;
    lastSpoken = text;
    lastSpokenAt = now;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    window.speechSynthesis.speak(utterance);
  }

  function haversine(aLat, aLon, bLat, bLon) {
    const r = 6371000;
    const p1 = (aLat * Math.PI) / 180;
    const p2 = (bLat * Math.PI) / 180;
    const dLat = ((bLat - aLat) * Math.PI) / 180;
    const dLon = ((bLon - aLon) * Math.PI) / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dLon / 2) ** 2;
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function distanceToRoute(lat, lon) {
    if (routeCoords.length < 2) return Infinity;
    let best = Infinity;
    for (let i = 1; i < routeCoords.length; i += 1) {
      const a = routeCoords[i - 1];
      const b = routeCoords[i];
      const ab = haversine(a[0], a[1], b[0], b[1]) || 1;
      const ap = haversine(a[0], a[1], lat, lon);
      const bp = haversine(b[0], b[1], lat, lon);
      const along = (ap * ap - bp * bp + ab * ab) / (2 * ab);
      const t = Math.max(0, Math.min(1, along / ab));
      const latP = a[0] + (b[0] - a[0]) * t;
      const lonP = a[1] + (b[1] - a[1]) * t;
      best = Math.min(best, haversine(lat, lon, latP, lonP));
    }
    return best;
  }

  function renderSteps() {
    if (!stepsEl) return;
    if (!routeSteps.length) {
      stepsEl.innerHTML = '<li class="route-empty">Search or tap the map to set a destination.</li>';
      return;
    }
    stepsEl.innerHTML = routeSteps
      .map((step, index) => {
        const km = step.distance_km == null ? '' : ` · ${Number(step.distance_km).toFixed(1)} km`;
        const cls = index === stepIndex ? ' class="route-current"' : '';
        return `<li${cls}>${esc(step.instruction)}${esc(km)}</li>`;
      })
      .join('');
  }

  function drawDestination(lat, lon, label) {
    destinationLayer.clearLayers();
    const marker = L.circleMarker([lat, lon], {
      radius: 8,
      color: '#fbbf24',
      fillColor: '#f59e0b',
      fillOpacity: 0.95,
      weight: 2,
    });
    marker.bindPopup(esc(label || 'Destination'));
    destinationLayer.addLayer(marker);
  }

  function drawRoute(coords) {
    routeLayer.clearLayers();
    if (coords.length < 2) return;
    routeLayer.addLayer(
      L.polyline(coords, { color: '#34d399', weight: 5, opacity: 0.9 })
    );
  }

  function origin() {
    if (gps && Date.now() - gpsAt < 60000) return { lat: gps.lat, lon: gps.lon };
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng };
  }

  async function buildRoute(reason) {
    if (!destination) return;
    const from = origin();
    setBanner(reason === 'reroute' ? 'Recalculating…' : 'Routing…');
    let res;
    try {
      res = await fetch('/api/route', {
        method: 'POST',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin: from,
          destination: { lat: destination.lat, lon: destination.lon },
          profile: profile(),
        }),
      });
    } catch {
      setBanner('Routing unavailable.');
      return;
    }
    if (res.status === 401) {
      setBanner('Set the API token to route.');
      return;
    }
    if (!res.ok) {
      let detail = 'No route.';
      try {
        const err = await res.json();
        if (err && err.detail) detail = String(err.detail);
      } catch {
        /* keep the short message */
      }
      setBanner(detail);
      return;
    }
    const data = await res.json();
    routeCoords = data.coordinates || [];
    routeSteps = data.steps || [];
    stepIndex = routeSteps.length ? 0 : -1;
    offRouteHits = 0;
    drawRoute(routeCoords);
    renderSteps();
    const first = routeSteps[0] && routeSteps[0].instruction;
    setBanner(first || 'Route ready.');
    if (reason === 'reroute') speak('Recalculating. ' + (first || ''), true);
    else if (first) speak(first, true);
    if (!follow && routeCoords.length) map.fitBounds(routeCoords, { padding: [28, 28] });
  }

  function advanceStep(lat, lon) {
    if (!routeSteps.length || !routeCoords.length) return;
    let nearest = 0;
    let best = Infinity;
    routeCoords.forEach((coord, index) => {
      const dist = haversine(lat, lon, coord[0], coord[1]);
      if (dist < best) {
        best = dist;
        nearest = index;
      }
    });
    let next = 0;
    routeSteps.forEach((step, index) => {
      if ((step.begin_index || 0) <= nearest) next = index;
    });
    if (next !== stepIndex) {
      stepIndex = next;
      renderSteps();
      const text = routeSteps[next] && routeSteps[next].instruction;
      if (text) {
        setBanner(text);
        speak(text, false);
      }
    }
  }

  function onFix(pos) {
    gps = { lat: pos.coords.latitude, lon: pos.coords.longitude };
    gpsAt = Date.now();
    gpsLayer.clearLayers();
    gpsLayer.addLayer(
      L.circleMarker([gps.lat, gps.lon], {
        radius: 7,
        color: '#38bdf8',
        fillColor: '#0ea5e9',
        fillOpacity: 0.95,
        weight: 2,
      })
    );
    if (follow) map.panTo([gps.lat, gps.lon]);
    if (!destination || routeCoords.length < 2) return;
    advanceStep(gps.lat, gps.lon);
    const off = distanceToRoute(gps.lat, gps.lon);
    if (off > REROUTE_METERS) offRouteHits += 1;
    else offRouteHits = 0;
    const now = Date.now();
    if (
      follow &&
      offRouteHits >= REROUTE_HITS &&
      now - lastRerouteAt > REROUTE_COOLDOWN_MS
    ) {
      lastRerouteAt = now;
      offRouteHits = 0;
      buildRoute('reroute');
    }
  }

  function onFixError() {
    setBanner('Location permission is off. Tap the map to route from the map center.');
  }

  function setFollow(on) {
    follow = on;
    if (followBtn) followBtn.textContent = on ? 'Following' : 'Follow';
    if (followBtn) followBtn.classList.toggle('is-on', on);
    if (watchId !== null) {
      navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }
    if (!on) return;
    if (!navigator.geolocation) {
      onFixError();
      return;
    }
    watchId = navigator.geolocation.watchPosition(onFix, onFixError, {
      enableHighAccuracy: true,
      maximumAge: 2000,
      timeout: 15000,
    });
  }

  function chooseDestination(lat, lon, label) {
    destination = { lat, lon, label };
    drawDestination(lat, lon, label);
    if (resultsEl) resultsEl.hidden = true;
    buildRoute('new');
  }

  async function runSearch() {
    if (!searchInput || !resultsEl) return;
    const q = searchInput.value.trim();
    if (q.length < 2) {
      resultsEl.hidden = true;
      resultsEl.innerHTML = '';
      return;
    }
    let res;
    try {
      res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}&limit=6`, { headers: headers() });
    } catch {
      return;
    }
    if (res.status === 401) {
      resultsEl.hidden = false;
      resultsEl.innerHTML = '<li>Set the API token in the node panel.</li>';
      return;
    }
    if (!res.ok) {
      resultsEl.hidden = false;
      resultsEl.innerHTML = '<li>Geocoder is not running. Start the nav profile.</li>';
      return;
    }
    const data = await res.json();
    const rows = data.results || [];
    if (!rows.length) {
      resultsEl.hidden = false;
      resultsEl.innerHTML = '<li>No matches.</li>';
      return;
    }
    resultsEl.hidden = false;
    resultsEl.innerHTML = rows
      .map(
        (row, index) =>
          `<li><button type="button" data-i="${index}">${esc(row.label)}</button></li>`
      )
      .join('');
    resultsEl.querySelectorAll('button').forEach((button) => {
      button.addEventListener('click', () => {
        const row = rows[Number(button.getAttribute('data-i'))];
        if (!row) return;
        searchInput.value = row.label;
        chooseDestination(row.lat, row.lon, row.label);
      });
    });
  }

  async function refreshCameras() {
    const here = gps || { lat: map.getCenter().lat, lon: map.getCenter().lng };
    let res;
    try {
      res = await fetch(
        `/api/cameras?lat=${encodeURIComponent(here.lat)}&lon=${encodeURIComponent(here.lon)}&radius_km=40`,
        { headers: headers() }
      );
    } catch {
      return;
    }
    if (!camContainer) return;
    if (res.status === 401) {
      camContainer.textContent = 'Set the API token to load cameras.';
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    cameraLayer.clearLayers();
    if (!data.configured) {
      camContainer.textContent = 'No OHGO_API_KEY set.';
      if (camList) camList.innerHTML = '';
      return;
    }
    if (data.status === 'unauthorized') {
      camContainer.textContent = 'OHGO rejected the API key.';
      return;
    }
    const cameras = data.cameras || [];
    if (!cameras.length) {
      camContainer.textContent = 'No cameras in range.';
      if (camList) camList.innerHTML = '';
      return;
    }
    cameras.slice(0, 60).forEach((cam) => {
      const marker = L.circleMarker([cam.lat, cam.lon], {
        radius: 5,
        color: '#fb7185',
        fillColor: '#e11d48',
        fillOpacity: 0.85,
        weight: 1,
      });
      marker.on('click', () => showCamera(cam));
      cameraLayer.addLayer(marker);
    });
    if (camList) {
      camList.innerHTML = cameras
        .slice(0, 12)
        .map(
          (cam) =>
            `<button type="button" data-id="${esc(cam.id)}">${esc(cam.name)} <span>${esc(cam.distance_km)} km</span></button>`
        )
        .join('');
      camList.querySelectorAll('button').forEach((button) => {
        button.addEventListener('click', () => {
          const cam = cameras.find((row) => row.id === button.getAttribute('data-id'));
          if (cam) showCamera(cam);
        });
      });
    }
    if (!camContainer.querySelector('img')) {
      camContainer.textContent = `${cameras.length} cameras nearby. Tap one.`;
    }
  }

  async function showCamera(cam) {
    if (!camContainer) return;
    camContainer.textContent = 'Loading snapshot…';
    let res;
    try {
      res = await fetch(`/api/cameras/${encodeURIComponent(cam.id)}/snap`, { headers: headers() });
    } catch {
      camContainer.textContent = 'Snapshot unavailable.';
      return;
    }
    if (!res.ok) {
      camContainer.textContent = 'Snapshot unavailable.';
      return;
    }
    const blob = await res.blob();
    if (snapUrl) URL.revokeObjectURL(snapUrl);
    snapUrl = URL.createObjectURL(blob);
    camContainer.innerHTML = `<img alt="${esc(cam.name)}" src="${snapUrl}" /><p>${esc(cam.name)}</p>`;
    map.panTo([cam.lat, cam.lon]);
  }

  map.on('click', (event) => {
    chooseDestination(event.latlng.lat, event.latlng.lng, 'Pinned destination');
  });

  const navForm = document.getElementById('nav-bar');
  if (navForm) navForm.addEventListener('submit', (event) => event.preventDefault());

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(runSearch, 300);
    });
    searchInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        const first = resultsEl && resultsEl.querySelector('button');
        if (first) first.click();
        else runSearch();
      }
    });
  }
  if (profileEl) profileEl.addEventListener('change', () => buildRoute('new'));
  if (followBtn) followBtn.addEventListener('click', () => setFollow(!follow));

  map.on('moveend', () => {
    window.clearTimeout(map._camTimer);
    map._camTimer = window.setTimeout(refreshCameras, 400);
  });

  const tiles = L.tileLayer('/tiles/styles/basic-preview/{z}/{x}/{y}.png', {
    maxZoom: 20,
    maxNativeZoom: 14,
    attribution: '&copy; OpenStreetMap',
  });
  tiles.on('tileerror', () => {
    if (tileWarned || !tileStatus) return;
    tileWarned = true;
    tileStatus.hidden = false;
  });
  tiles.addTo(map);

  renderSteps();
  refreshCameras();
  window.setInterval(refreshCameras, 30000);

  window.SovereignNav = {
    onToken() {
      refreshCameras();
      if (destination) buildRoute('new');
    },
  };
})();
