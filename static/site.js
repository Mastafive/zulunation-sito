// Zulu Nation Italia — piccole funzioni lato browser
(function () {
  // copia link
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.copy');
    if (!b) return;
    navigator.clipboard && navigator.clipboard.writeText(b.dataset.url).then(function () {
      var t = b.textContent; b.textContent = 'Copiato!'; setTimeout(function () { b.textContent = t; }, 1600);
    });
  });

  // lightbox immagini negli articoli
  document.addEventListener('click', function (e) {
    var a = e.target.closest('.prose a.lightbox');
    if (!a) return;
    e.preventDefault();
    var box = document.createElement('div');
    box.className = 'lb';
    var img = document.createElement('img');
    img.src = a.getAttribute('href');
    img.alt = '';
    box.appendChild(img);
    box.addEventListener('click', function () { box.remove(); });
    document.addEventListener('keydown', function esc(k) { if (k.key === 'Escape') { box.remove(); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(box);
  });

  // ricerca
  var out = document.getElementById('results');
  var q = document.getElementById('q');
  if (!out || !q) return;
  var count = document.getElementById('qcount');
  var data = [];
  var norm = function (s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var mesi = ['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre'];
  var fmt = function (d) { var p = d.split('-'); return (+p[2]) + ' ' + mesi[+p[1] - 1] + ' ' + p[0]; };

  function render() {
    var terms = norm(q.value).split(/\s+/).filter(Boolean);
    var list = !terms.length ? data.slice(0, 24) : data.filter(function (p) {
      var hay = norm(p.t + ' ' + p.l.join(' ') + ' ' + p.e);
      return terms.every(function (t) { return hay.indexOf(t) > -1; });
    });
    count.textContent = terms.length ? list.length + ' risultati' : '';
    out.innerHTML = list.slice(0, 120).map(function (p) {
      return '<article class="card card-md"><a class="card-img" href="' + p.u + '">' +
        (p.i ? '<img src="' + esc(p.i) + '" alt="" loading="lazy">' : '<div class="ph"><span>ZN</span></div>') +
        '</a><div class="card-body"><span class="kicker">' + esc(p.l[0] || 'Zulu Nation') + '</span>' +
        '<h3 class="card-title"><a href="' + p.u + '">' + esc(p.t) + '</a></h3>' +
        '<div class="byline">' + fmt(p.d) + '</div></div></article>';
    }).join('') || '<p>Nessun risultato.</p>';
    var url = new URL(location.href);
    if (q.value) url.searchParams.set('q', q.value); else url.searchParams.delete('q');
    history.replaceState(null, '', url);
  }

  fetch(out.dataset.index).then(function (r) { return r.json(); }).then(function (j) {
    data = j;
    var init = new URLSearchParams(location.search).get('q');
    if (init) q.value = init;
    render();
  });
  var timer;
  q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(render, 120); });
})();
