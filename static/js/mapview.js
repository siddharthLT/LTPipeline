// Mapped universe map: clustered pins for the filtered companies; filtering by region/country/state zooms to what is left.
(function () {
  var el = document.getElementById('mu-map'), data = document.getElementById('mu-points');
  if (!el || !data || !window.L) return;
  var pts = JSON.parse(data.textContent);
  var map = L.map(el, { worldCopyJump: true, minZoom: 2, zoomControl: true }).setView([30, -20], 2);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; geocoding &copy; OpenStreetMap contributors', maxZoom: 13
  }).addTo(map);
  // borders and place names on top, so it is clear which side of the line a pin is on
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 13, pane: 'shadowPane' }).addTo(map);

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function pin(p) {
    return L.divIcon({ className: 'mu-pin' + (p.pp ? ' mu-pin--pipe' : p.g === 'city' ? ' mu-pin--approx' : ''), iconSize: [14, 14], iconAnchor: [7, 7] });
  }
  var cluster = L.markerClusterGroup({
    maxClusterRadius: pts.length > 150 ? 44 : 22, spiderfyOnMaxZoom: true, showCoverageOnHover: false,
    iconCreateFunction: function (c) {
      var n = c.getChildCount();
      // teal: none in the pipeline, deep blue: some, red: all (recomputed for every cluster and sub-cluster as you zoom)
      var kids = c.getAllChildMarkers(), inPipe = kids.filter(function (m) { return m.options.pipe; }).length;
      var allPipe = inPipe === kids.length, somePipe = inPipe > 0 && !allPipe;
      return L.divIcon({ html: '<span>' + n + '</span>', className: 'mu-cluster' + (allPipe ? ' mu-cluster--pipe' : somePipe ? ' mu-cluster--mixed' : '') + (n >= 100 ? ' mu-cluster--l' : n >= 10 ? ' mu-cluster--m' : ''), iconSize: [34, 34] });
    }
  });
  var bounds = [];
  pts.forEach(function (p) {
    var place = [p.c, p.co === 'United States' ? p.st : '', p.co].filter(Boolean).join(', ');
    var site = p.u || (p.d ? 'https://' + p.d : '');
    var logo = p.l ? '<img class="mu-pop__logo" src="' + esc(p.l) + '" alt="" onerror="this.remove()">' : '';
    var html = '<div class="mu-pop">' + logo + '<div><strong>' + esc(p.n) + '</strong><span class="mu-pop__seg">' + esc(p.s) + '</span></div></div>' +
      '<p class="mu-pop__addr">' + esc(p.g === 'city' ? place + ' (approximate)' : (p.a || place)) + '</p>' +
      (p.pp ? '<a class="mu-pop__pipe" href="' + esc(p.pp) + '">In pipeline &middot; open account</a><br>' : '') +
      (site ? '<a class="mu-pop__link" href="' + esc(site) + '" target="_blank" rel="noopener">' + esc(p.d || site) + '</a>' : '');
    cluster.addLayer(L.marker([p.la, p.ln], { icon: pin(p), title: p.n, pipe: !!p.pp }).bindPopup(html, { minWidth: 250, maxWidth: 300 }));
    bounds.push([p.la, p.ln]);
  });
  map.addLayer(cluster);
  var filtered = /[?&](q|segment|region|country|state|logo|pipe)=/.test(location.search);
  if (bounds.length && filtered) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 10 });
  else if (bounds.length) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 4 });
  setTimeout(function () { map.invalidateSize(); }, 100);
})();
