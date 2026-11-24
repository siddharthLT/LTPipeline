/* Pipeline sign-in: a slowly turning globe of dots, with biotech hubs lighting up and arcs linking them.
   three.js r128 (global build) does the drawing; every look comes from the Lunartree teal palette. */
(function () {
  var host = document.querySelector('[data-globe]');
  if (!host || !window.THREE) return;
  var THREE = window.THREE;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // lat, lon: where a hub appears. The first few light up first, so the opening seconds already have something to look at.
  var HUBS = [
    [42.36, -71.06], [37.77, -122.42], [47.56, 7.59], [51.5, -0.12], [19.08, 72.88], [31.23, 121.47], [32.72, -117.16], [52.2, 0.12],
    [35.78, -78.64], [17.39, 78.49], [1.35, 103.82], [35.68, 139.69], [48.14, 11.58], [55.68, 12.57], [39.95, -75.17], [37.57, 126.98],
    [12.97, 77.59], [32.08, 34.78], [43.65, -79.38], [-33.87, 151.21], [59.33, 18.07], [48.86, 2.35], [23.02, 72.57], [31.3, 120.6],
    [40.72, -74.17], [47.37, 8.54], [45.46, 9.19], [53.35, -6.26], [49.28, -123.12], [39.9, 116.4], [25.2, 55.27], [-23.55, -46.63],
    [-26.2, 28.05], [50.85, 4.35]
  ];
  var LINKS = [[0, 2], [2, 4], [4, 10], [10, 11], [1, 5], [3, 0], [6, 1], [7, 3], [5, 11], [9, 4], [13, 20], [8, 0], [17, 4], [18, 0], [14, 3]];
  var CYCLE = 26, STEP = 0.5;
  var COL = { deep: 0x06383B, teal: 0x078E93, mid: 0x67C8CC, light: 0xA9EBEE, orange: 0xDC5800 };

  function toVec(lat, lon, r) {
    var phi = (90 - lat) * Math.PI / 180, theta = (lon + 180) * Math.PI / 180;
    return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
  }

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (e) { return; }  // no WebGL: the panel keeps its gradient
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  renderer.domElement.setAttribute('aria-hidden', 'true');

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
  var globe = new THREE.Group();
  scene.add(globe);
  globe.rotation.x = 0.38;  // axial tilt

  // the sphere itself: deep teal, a little lighter at the rim
  globe.add(new THREE.Mesh(new THREE.SphereGeometry(0.985, 64, 64), new THREE.ShaderMaterial({
    uniforms: { cDeep: { value: new THREE.Color(COL.deep) }, cRim: { value: new THREE.Color(COL.teal) } },
    vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 wp = modelMatrix*vec4(position,1.0); vN = normalize(mat3(modelMatrix)*position); vV = normalize(cameraPosition-wp.xyz); gl_Position = projectionMatrix*viewMatrix*wp; }',
    fragmentShader: 'uniform vec3 cDeep; uniform vec3 cRim; varying vec3 vN; varying vec3 vV; void main(){ float f = 1.0-max(dot(vN,vV),0.0); gl_FragColor = vec4(mix(cDeep, cRim, pow(f,3.0)*0.55), 1.0); }'
  })));

  // a soft glow just outside the sphere
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.13, 64, 64), new THREE.ShaderMaterial({
    uniforms: { c: { value: new THREE.Color(COL.mid) } }, transparent: true, side: THREE.BackSide, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 wp = modelMatrix*vec4(position,1.0); vN = normalize(mat3(modelMatrix)*position); vV = normalize(cameraPosition-wp.xyz); gl_Position = projectionMatrix*viewMatrix*wp; }',
    fragmentShader: 'uniform vec3 c; varying vec3 vN; varying vec3 vV; void main(){ float i = pow(clamp(-dot(vN,vV),0.0,1.0),1.6); gl_FragColor = vec4(c, i*0.55); }'
  })));

  // graticule
  var lines = [];
  for (var la = -60; la <= 60; la += 30) for (var lo = -180; lo < 180; lo += 4) lines.push(toVec(la, lo, 1.002), toVec(la, lo + 4, 1.002));
  for (var lo2 = -180; lo2 < 180; lo2 += 30) for (var la2 = -84; la2 < 84; la2 += 4) lines.push(toVec(la2, lo2, 1.002), toVec(la2 + 4, lo2, 1.002));
  globe.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(lines),
    new THREE.LineBasicMaterial({ color: COL.mid, transparent: true, opacity: 0.07, depthWrite: false })));

  // shared by the land dots, the hubs and their rings
  var VERT = [
    'uniform float uTime; uniform float uScale; uniform float uSize; uniform float uCycle;',
    'attribute float aBirth; attribute float aHot; varying float vFacing; varying float vAge; varying float vHot; varying float vFade;',
    'void main(){',
    '  vec4 wp = modelMatrix*vec4(position,1.0);',
    '  vec3 n = normalize(mat3(modelMatrix)*position);',
    '  vFacing = dot(n, normalize(cameraPosition-wp.xyz));',
    '  vAge = uTime - aBirth; vHot = aHot;',
    '  vFade = 1.0 - smoothstep(uCycle-4.0, uCycle-1.0, uTime);',
    '  float grow = clamp(vAge/0.9, 0.0, 1.0); grow = 1.0 - pow(1.0-grow, 3.0);',
    '  vec4 mv = viewMatrix*wp;',
    '  gl_PointSize = uSize*uScale*grow*vFade/(-mv.z);',
    '  gl_Position = projectionMatrix*mv;',
    '}'
  ].join('\n');
  function pointMaterial(frag, size, extra) {
    return new THREE.ShaderMaterial({
      uniforms: Object.assign({ uTime: { value: 0 }, uScale: { value: 400 }, uSize: { value: size }, uCycle: { value: CYCLE },
        cA: { value: new THREE.Color(COL.light) }, cB: { value: new THREE.Color(COL.orange) } }, extra || {}),
      vertexShader: VERT, fragmentShader: frag, transparent: true, depthWrite: false
    });
  }

  // land: one soft dot per grid cell that sits on land
  var land = new Float32Array(0);
  var landMat = new THREE.ShaderMaterial({
    uniforms: { uScale: { value: 400 }, uSize: { value: 0.016 }, cA: { value: new THREE.Color(COL.mid) } },
    vertexShader: 'uniform float uScale; uniform float uSize; varying float vFacing; void main(){ vec4 wp = modelMatrix*vec4(position,1.0); vec3 n = normalize(mat3(modelMatrix)*position); vFacing = dot(n, normalize(cameraPosition-wp.xyz)); vec4 mv = viewMatrix*wp; gl_PointSize = uSize*uScale/(-mv.z); gl_Position = projectionMatrix*mv; }',
    fragmentShader: 'uniform vec3 cA; varying float vFacing; void main(){ float d = length(gl_PointCoord-0.5)*2.0; float a = smoothstep(1.0,0.55,d)*smoothstep(0.0,0.4,vFacing); if (a < 0.01) discard; gl_FragColor = vec4(cA, a*0.9); }',
    transparent: true, depthWrite: false
  });
  var landPts = new THREE.Points(new THREE.BufferGeometry(), landMat);
  globe.add(landPts);
  var src = host.getAttribute('data-dots');
  fetch(src).then(function (r) { return r.json(); }).then(function (flat) {
    var v = [];
    for (var i = 0; i < flat.length; i += 2) v.push(toVec(flat[i], flat[i + 1], 1.0));
    landPts.geometry.setFromPoints(v);
    if (reduce) frame(performance.now());
  }).catch(function () {});

  // hubs
  var pos = [], birth = [], hot = [];
  HUBS.forEach(function (h, i) {
    var v = toVec(h[0], h[1], 1.004);
    pos.push(v.x, v.y, v.z);
    birth.push(0.7 + i * STEP + (i % 3) * 0.12);
    hot.push(i % 5 === 3 ? 1 : 0);  // a few in orange: the new ones
  });
  function hubGeometry() {
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('aBirth', new THREE.Float32BufferAttribute(birth, 1));
    g.setAttribute('aHot', new THREE.Float32BufferAttribute(hot, 1));
    return g;
  }
  var COLOR = 'uniform vec3 cA; uniform vec3 cB; varying float vFacing; varying float vAge; varying float vHot; varying float vFade;';
  var core = new THREE.Points(hubGeometry(), pointMaterial(COLOR + [
    'void main(){ if (vFacing < 0.02 || vAge < 0.0) discard;',
    '  float d = length(gl_PointCoord-0.5)*2.0; float a = smoothstep(1.0,0.2,d);',
    '  vec3 c = mix(cA, cB, vHot); gl_FragColor = vec4(mix(c, vec3(1.0), smoothstep(0.5,0.0,d)*0.6), a*vFade); }'].join('\n'), 0.05));
  var rings = new THREE.Points(hubGeometry(), pointMaterial(COLOR + [
    'void main(){ if (vFacing < 0.02 || vAge < 0.0) discard;',
    '  float d = length(gl_PointCoord-0.5)*2.0; float ph = fract(vAge*0.42); float a = smoothstep(0.1,0.0,abs(d-ph))*(1.0-ph)*smoothstep(0.0,0.5,vAge);',
    '  gl_FragColor = vec4(mix(cA, cB, vHot), a*0.85*vFade); }'].join('\n'), 0.19));
  globe.add(rings, core);

  // arcs between hubs, drawn when both ends are lit
  var arcs = LINKS.map(function (l) {
    var a = toVec(HUBS[l[0]][0], HUBS[l[0]][1], 1), b = toVec(HUBS[l[1]][0], HUBS[l[1]][1], 1);
    var ang = a.angleTo(b), pts = [];
    for (var i = 0; i <= 56; i++) {
      var u = i / 56, p = new THREE.Vector3().copy(a).multiplyScalar(Math.sin((1 - u) * ang)).add(b.clone().multiplyScalar(Math.sin(u * ang))).divideScalar(Math.sin(ang));
      pts.push(p.normalize().multiplyScalar(1.004 + 0.22 * Math.sin(Math.PI * u) * Math.min(ang / 1.4, 1)));
    }
    var line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: COL.light, transparent: true, opacity: 0, depthWrite: false }));
    line.geometry.setDrawRange(0, 0);
    globe.add(line);
    return { line: line, n: pts.length, at: Math.max(birth[l[0]], birth[l[1]]) + 0.5 };
  });

  var size = { w: 0, h: 0 };
  function resize() {
    var w = host.clientWidth, h = host.clientHeight;
    if (!w || !h || (w === size.w && h === size.h)) return;
    size = { w: w, h: h };
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    var tan = Math.tan(camera.fov * Math.PI / 360);
    camera.position.set(0, 0, (h / 2) / (0.34 * Math.min(w, h) * tan));
    camera.updateProjectionMatrix();
    var scale = h * dpr / (2 * tan);  // world units to pixels at distance 1
    [landMat, core.material, rings.material].forEach(function (m) { m.uniforms.uScale.value = scale; });
  }
  resize();
  if (window.ResizeObserver) new ResizeObserver(resize).observe(host); else window.addEventListener('resize', resize);

  var tiltTo = 0.38, tilt = 0.38;
  host.addEventListener('pointermove', function (e) {
    var r = host.getBoundingClientRect();
    tiltTo = 0.38 + ((e.clientY - r.top) / r.height - 0.5) * 0.3;
  });

  var t0 = performance.now(), last = t0, spin = 2.2;
  function frame(now) {
    var dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    var t = reduce ? CYCLE * 0.8 : ((now - t0) / 1000) % CYCLE;
    if (!reduce) { spin += dt * 0.16; }
    globe.rotation.y = spin;
    tilt += (tiltTo - tilt) * Math.min(dt * 3, 1);
    globe.rotation.x = tilt;
    core.material.uniforms.uTime.value = rings.material.uniforms.uTime.value = t;
    var fade = 1 - Math.min(Math.max((t - (CYCLE - 4)) / 3, 0), 1);
    arcs.forEach(function (a) {
      var p = Math.min(Math.max((t - a.at) / 1.8, 0), 1);
      a.line.geometry.setDrawRange(0, Math.floor(p * a.n));
      a.line.material.opacity = 0.55 * Math.min(p * 3, 1) * fade;
    });
    resize();
    renderer.render(scene, camera);
    if (!reduce && !document.hidden) loop();
  }
  var raf = 0;
  function loop() { if (!raf) raf = requestAnimationFrame(function (n) { raf = 0; frame(n); }); }
  if (reduce) { frame(performance.now()); }
  else {
    loop();
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { last = performance.now(); loop(); } });
  }
  host.classList.add('is-live');
})();
