/* Product usage sign-in: a small dashboard that draws itself, then keeps refreshing with new numbers.
   A journey Sankey, an action funnel, a trend line, daily bars and an engagement donut, all plain SVG. */
(function () {
  var host = document.querySelector('[data-usageviz]');
  if (!host) return;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, kids, ns) {
    var e = ns ? document.createElementNS(NS, tag) : document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  var svg = function (tag, attrs, kids) { return el(tag, attrs, kids, true); };
  function rnd(a, b) { return a + Math.random() * (b - a); }
  function card(i, eyebrow, title, body, wide, lower) {
    return el('section', { 'class': 'uviz__card' + (wide ? ' uviz__card--wide' : '') + (lower ? ' uviz__card--lower' : ''), style: '--i:' + i }, [
      el('header', { 'class': 'uviz__head' }, [el('span', { 'class': 'uviz__eyebrow', text: eyebrow }), el('strong', { text: title })]), body]);
  }
  function tween(node, to, ms, fmt) {  // count a number up
    var from = parseFloat(node.getAttribute('data-v')) || 0, t0 = performance.now();
    node.setAttribute('data-v', to);
    if (reduce) { node.textContent = fmt(to); return; }
    (function step(now) {
      var k = Math.min((now - t0) / ms, 1), e = 1 - Math.pow(1 - k, 3);
      node.textContent = fmt(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  /* ---- journey Sankey ---- */
  var NODES = [
    ['open', 0, 'Opened'], ['look', 1, 'Looked'], ['stop1', 1, 'Stopped'], ['dig', 2, 'Dug in'], ['stop2', 2, 'Stopped'],
    ['work', 3, 'Took action'], ['stop3', 3, 'Stopped'], ['reach', 4, 'Reached out']];
  var LINKS = [['open', 'look', 66], ['open', 'stop1', 34], ['look', 'dig', 44], ['look', 'stop2', 22], ['dig', 'work', 30], ['dig', 'stop3', 14], ['work', 'reach', 18], ['work', 'stop3', 12]];
  function sankey() {
    var W = 560, H = 140, NW = 10, PAD = 9, cols = 5, top = 4;
    var byId = {}, val = {};
    NODES.forEach(function (n) { byId[n[0]] = { id: n[0], col: n[1], label: n[2], stop: n[0].indexOf('stop') === 0, out: 0, in: 0 }; val[n[0]] = 0; });
    LINKS.forEach(function (l) { val[l[0]] = Math.max(val[l[0]], 0); });
    var sIn = {}, sOut = {};
    LINKS.forEach(function (l) { sOut[l[0]] = (sOut[l[0]] || 0) + l[2]; sIn[l[1]] = (sIn[l[1]] || 0) + l[2]; });
    NODES.forEach(function (n) { byId[n[0]].v = Math.max(sIn[n[0]] || 0, sOut[n[0]] || 0); });
    var perCol = [0, 1, 2, 3, 4].map(function (c) { return NODES.filter(function (n) { return n[1] === c; }); });
    var avail = H - top - 8, scale = Infinity;
    perCol.forEach(function (ns) {
      var sum = ns.reduce(function (a, n) { return a + byId[n[0]].v; }, 0);
      scale = Math.min(scale, (avail - PAD * (ns.length - 1)) / sum);
    });
    var xs = [0, 1, 2, 3, 4].map(function (c) { return 6 + (W - 110 - 6) * c / (cols - 1); });
    perCol.forEach(function (ns, c) {
      var h = ns.reduce(function (a, n) { return a + byId[n[0]].v * scale; }, 0) + PAD * (ns.length - 1), y = top + (avail - h) / 2;
      ns.forEach(function (n) { var o = byId[n[0]]; o.x = xs[c]; o.y = y; o.h = o.v * scale; y += o.h + PAD; });
    });
    var g = svg('g', {}), flow = svg('g', {}), nodes = svg('g', {});
    LINKS.forEach(function (l, i) {
      var a = byId[l[0]], b = byId[l[1]], w = l[2] * scale;
      var y0 = a.y + a.out + w / 2, y1 = b.y + b['in'] + w / 2;
      a.out += w; b['in'] += w;
      var x0 = a.x + NW, x1 = b.x, xm = (x0 + x1) / 2;
      var d = 'M' + x0 + ',' + y0 + ' C' + xm + ',' + y0 + ' ' + xm + ',' + y1 + ' ' + x1 + ',' + y1;
      g.appendChild(svg('path', { d: d, 'class': 'uviz__link' + (b.stop ? ' is-stop' : ''), 'stroke-width': Math.max(w, 1), style: '--d:' + (0.15 + i * 0.09) + 's' }));
      if (!b.stop) flow.appendChild(svg('path', { d: d, 'class': 'uviz__flow', 'stroke-width': Math.max(Math.min(w * 0.3, 4), 1.5), style: '--d:' + (i * 0.37) + 's' }));
    });
    NODES.forEach(function (n, i) {
      var o = byId[n[0]];
      nodes.appendChild(svg('rect', { x: o.x, y: o.y, width: NW, height: Math.max(o.h, 2), rx: 2, 'class': 'uviz__node' + (o.stop ? ' is-stop' : ''), style: '--d:' + (i * 0.07) + 's' }));
      if (!o.stop || n[1] === 1) nodes.appendChild(svg('text', { x: o.x + NW + 6, y: o.y + Math.max(o.h, 2) / 2, dy: '0.35em', 'class': 'uviz__lbl', text: o.label }));
    });
    return svg('svg', { viewBox: '0 0 ' + W + ' ' + H, 'class': 'uviz__svg', role: 'img', 'aria-label': 'Journey Sankey' }, [g, flow, nodes]);
  }

  /* ---- action funnel ---- */
  var STEPS = ['Opened BioLens', 'Looked at companies', 'Dug into profiles', 'Took an action', 'Reached out'];
  function funnel() {
    var rows = STEPS.map(function (s) {
      var n = el('b', { text: '0', 'data-v': '0' }), bar = el('i', {});
      return { n: n, bar: bar, node: el('li', { 'class': 'uviz__frow' }, [el('span', { text: s }), el('div', { 'class': 'uviz__fbar' }, [bar]), n]) };
    });
    var ul = el('ul', { 'class': 'uviz__funnel' }, rows.map(function (r) { return r.node; }));
    ul.refresh = function () {
      var v = rnd(120, 190), vals = [v];
      for (var i = 1; i < rows.length; i++) vals.push(vals[i - 1] * rnd(0.52, 0.8));
      rows.forEach(function (r, i) {
        r.bar.style.width = (vals[i] / vals[0] * 100).toFixed(1) + '%';
        r.bar.style.transitionDelay = (i * 0.12) + 's';
        tween(r.n, Math.round(vals[i]), 1100, function (x) { return Math.round(x); });
      });
    };
    return ul;
  }

  /* ---- trend line ---- */
  function smooth(p) {
    var d = 'M' + p[0][0] + ',' + p[0][1];
    for (var i = 0; i < p.length - 1; i++) {
      var a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
      d += ' C' + (b[0] + (c[0] - a[0]) / 6) + ',' + (b[1] + (c[1] - a[1]) / 6) + ' ' + (c[0] - (e[0] - b[0]) / 6) + ',' + (c[1] - (e[1] - b[1]) / 6) + ' ' + c[0] + ',' + c[1];
    }
    return d;
  }
  function trend() {
    var W = 270, H = 96, wrap = el('div', { 'class': 'uviz__trend' });
    wrap.refresh = function () {
      var pts = [], y = rnd(58, 74);
      for (var i = 0; i < 16; i++) { y = Math.max(10, Math.min(82, y - rnd(-8, 12))); pts.push([8 + i * (W - 16) / 15, y]); }
      var line = smooth(pts), id = 'ug' + Math.floor(Math.random() * 1e6);
      var s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, 'class': 'uviz__svg', role: 'img', 'aria-label': 'Activity trend' }, [
        svg('defs', {}, [svg('linearGradient', { id: id, x1: 0, y1: 0, x2: 0, y2: 1 }, [svg('stop', { offset: '0%', 'stop-color': '#A9EBEE', 'stop-opacity': '.45' }), svg('stop', { offset: '100%', 'stop-color': '#A9EBEE', 'stop-opacity': '0' })])]),
        svg('path', { d: line + ' L' + pts[15][0] + ',' + H + ' L' + pts[0][0] + ',' + H + ' Z', fill: 'url(#' + id + ')', 'class': 'uviz__area' }),
        svg('path', { d: line, 'class': 'uviz__line', pathLength: 1 }),
        svg('circle', { r: 4, 'class': 'uviz__dot' }, reduce ? [] : [svg('animateMotion', { dur: '1.8s', fill: 'freeze', path: line, calcMode: 'spline', keySplines: '.3 .6 .3 1', keyTimes: '0;1' })])]);
      if (reduce) { var c = s.querySelector('circle'); c.setAttribute('cx', pts[15][0]); c.setAttribute('cy', pts[15][1]); }
      wrap.textContent = ''; wrap.appendChild(s);
    };
    return wrap;
  }

  /* ---- daily bars ---- */
  function bars() {
    var n = 18, kids = [];
    for (var i = 0; i < n; i++) kids.push(el('i', { style: '--h:0%;--k:' + i }));
    var box = el('div', { 'class': 'uviz__bars' }, kids);
    box.refresh = function () { kids.forEach(function (b) { b.style.setProperty('--h', rnd(12, 100).toFixed(0) + '%'); }); };
    return box;
  }

  /* ---- engagement donut ---- */
  var TIERS = ['Power', 'Active', 'Browser', 'Low'];
  function donut() {
    var R = 38, C = 2 * Math.PI * R, segs = TIERS.map(function (t, i) { return svg('circle', { cx: 50, cy: 50, r: R, 'class': 'uviz__seg uviz__seg--' + i, 'stroke-dasharray': '0 ' + C, transform: 'rotate(-90 50 50)' }); });
    var num = el('b', { text: '0', 'data-v': '0' });
    var legend = el('ul', { 'class': 'uviz__legend' }, TIERS.map(function (t, i) { return el('li', {}, [el('i', { 'class': 'uviz__sw uviz__sw--' + i }), el('span', { text: t })]); }));
    var box = el('div', { 'class': 'uviz__donut' }, [
      el('div', { 'class': 'uviz__ring' }, [svg('svg', { viewBox: '0 0 100 100', 'class': 'uviz__svg', role: 'img', 'aria-label': 'Engagement tiers' }, [svg('circle', { cx: 50, cy: 50, r: R, 'class': 'uviz__track' })].concat(segs)), el('div', { 'class': 'uviz__center' }, [num, el('span', { text: 'users' })])]), legend]);
    box.refresh = function () {
      var w = [rnd(1, 3), rnd(2, 5), rnd(2, 5), rnd(1, 4)], sum = w.reduce(function (a, b) { return a + b; }, 0), off = 0;
      segs.forEach(function (s, i) {
        var len = Math.max(w[i] / sum * C - 2.5, 0.1);
        s.setAttribute('stroke-dasharray', len + ' ' + (C - len));
        s.setAttribute('stroke-dashoffset', -off);
        off += w[i] / sum * C;
      });
      tween(num, Math.round(rnd(24, 60)), 1100, function (x) { return Math.round(x); });
    };
    return box;
  }

  var sk = sankey(), fn = funnel(), tr = trend(), br = bars(), dn = donut();
  var grid = el('div', { 'class': 'uviz__grid' }, [
    card(0, 'Journeys', 'The paths people take', sk, true),
    card(1, 'Action funnel', 'How far users get', fn),
    card(2, 'Last 30 days', 'Activity', tr),
    card(3, 'Daily', 'Events per day', br, false, true),
    card(4, 'Engagement', 'Who is using it', dn, false, true)]);
  host.appendChild(grid);

  function play() { [fn, tr, br, dn].forEach(function (c) { c.refresh(); }); }
  // the first fill waits a beat so the cards can fade in first
  setTimeout(function () { host.classList.add('is-live'); play(); }, 350);
  if (!reduce) {
    setInterval(function () { if (!document.hidden) play(); }, 7000);
    // the Sankey re-draws its wipe on the same beat
    setInterval(function () { if (document.hidden) return; host.classList.remove('is-live'); void host.offsetWidth; host.classList.add('is-live'); }, 21000);
  }
})();
