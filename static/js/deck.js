// Hand Raisers deck: one slide at a time, scaled to the window, text shrunk to fit its box.
(function () {
  var deck = document.querySelector('[data-deck]');
  if (!deck) return;
  var canvas = deck.querySelector('[data-canvas]'), stage = deck.querySelector('[data-stage]'),
      slides = Array.from(deck.querySelectorAll('[data-slide]')),
      prev = deck.querySelector('[data-prev]'), next = deck.querySelector('[data-next]'),
      count = deck.querySelector('[data-count]'), bar = deck.querySelector('[data-progress]');
  var i = 0;
  try { i = Math.min(Math.max(parseInt(location.hash.slice(1), 10) - 1 || 0, 0), slides.length - 1); } catch (e) {}

  function scale() {
    var s = Math.min(stage.clientWidth / 1280, stage.clientHeight / 720) * 0.97;
    canvas.style.setProperty('--scale', s);
  }
  function shrink(el, min) {
    el.style.fontSize = '';
    var size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollHeight > el.clientHeight + 1 && size > min) { size -= 0.5; el.style.fontSize = size + 'px'; }
    return size;
  }
  function fit() {
    // Blocks in one row share the smallest size so a slide reads evenly.
    deck.querySelectorAll('.slide__main, .slide__sub').forEach(function (row) {
      var blocks = Array.from(row.querySelectorAll('.hr-fit')), low = 99;
      blocks.forEach(function (el) { low = Math.min(low, shrink(el, 12)); });
      blocks.forEach(function (el) { el.style.fontSize = low + 'px'; });
    });
    deck.querySelectorAll('.slide__table').forEach(function (el) { shrink(el, 11); });
  }
  function show(n) {
    i = Math.min(Math.max(n, 0), slides.length - 1);
    slides.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
    count.textContent = (i + 1) + ' / ' + slides.length;
    bar.style.width = ((i + 1) / slides.length * 100) + '%';
    prev.disabled = i === 0; next.disabled = i === slides.length - 1;
    try { history.replaceState(null, '', '#' + (i + 1)); } catch (e) {}
  }
  prev.addEventListener('click', function () { show(i - 1); });
  next.addEventListener('click', function () { show(i + 1); });
  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); show(i + 1); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); show(i - 1); }
    else if (e.key === 'Home') show(0);
    else if (e.key === 'End') show(slides.length - 1);
  });
  window.addEventListener('resize', scale);
  scale(); show(i);
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(fit);
  fit();
})();
