const code = new URLSearchParams(location.search).get('code');
if (!code) location.href = '/';

const $ = (id) => document.getElementById(id);
const num = (x) => Number(x).toLocaleString('id-ID', { maximumFractionDigits: 1 });
const fmtG = (g) => `${num(g)} g`;
const pct = (p) => (p >= 0.9995 ? '> 99,9%' : p > 0 && p < 0.0005 ? '< 0,1%' : `${num(p * 100)}%`);
const JENIS = { beri: 'Beri pakan', tahan: 'Ditahan', isi_ulang: 'Isi ulang' };
let chart = null;
let file = null;

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v; else n.setAttribute(k, v);
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(c ?? ''));
  return n;
}

async function api(path, options) {
  const r = await fetch(path, options);
  const j = await r.json().catch(() => ({ error: 'Respons server tidak valid.' }));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

async function load() {
  try {
    render(await api('/api/dashboard?code=' + encodeURIComponent(code)));
    $('loadErr').hidden = true;
  } catch (e) {
    $('loadErr').textContent = e.message;
    $('loadErr').hidden = false;
  }
}

function render(d) {
  const { device, stok, hari_ini } = d;
  $('dev').textContent = `${device.code} · mode ${device.mode} · porsi ${fmtG(device.porsi_g)}`;

  $('sisa').textContent = fmtG(stok.sisa_g);
  const bar = $('sisaBar');
  bar.firstElementChild.style.width = Math.min(100, stok.persen) + '%';
  bar.className = 'bar' + (stok.persen < 10 ? ' critical' : stok.persen < 20 ? ' low' : '');
  $('sisaSub').textContent = `${num(stok.persen)}% dari ${fmtG(stok.kapasitas_g)}`;

  if (stok.perkiraan_habis_hari == null) {
    $('habis').textContent = '–';
    $('habisSub').textContent = `butuh ≥ 3 hari data (sekarang ${stok.hari_data})`;
  } else {
    $('habis').textContent = `${num(stok.perkiraan_habis_hari)} hari`;
    const tgl = new Date(stok.perkiraan_habis_tanggal).toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'short' });
    $('habisSub').textContent = `±${tgl} · rata-rata ${fmtG(stok.rata_harian_g)}/hari`;
  }
  $('today').textContent = fmtG(hari_ini.pakan_g);
  $('todaySub').textContent = `${hari_ini.beri} kali diberi`;
  $('hold').textContent = `${hari_ini.tahan} kali`;

  const notes = $('notes');
  notes.replaceChildren(...d.notifikasi.map((n) => el('div', { class: `note ${n.level}` }, n.pesan)));
  if (!device.model_tersedia) {
    notes.append(el('div', { class: 'note mendesak' }, `Model untuk mode ${device.mode} belum tersedia, simulasi tidak bisa dijalankan.`));
  }

  drawChart(d.grafik);

  $('history').replaceChildren(...(d.riwayat.length ? d.riwayat.map((r) => el('tr', {},
    el('td', {}, r.ts.slice(5, 16).replace('-', '/')),
    el('td', {}, r.thumb ? el('img', { src: r.thumb, alt: '' }) : '–'),
    el('td', {}, el('span', { class: `badge ${r.jenis}` }, JENIS[r.jenis] || r.jenis)),
    el('td', {}, r.label ? `${r.label} (${pct(r.confidence)})` : '–'),
    el('td', {}, r.jenis === 'isi_ulang' ? `+${fmtG(r.gram)}` : r.gram ? `−${fmtG(r.gram)}` : '–'),
  )) : [el('tr', {}, el('td', { colspan: '5', class: 'muted' }, 'Belum ada riwayat.'))]));
}

function drawChart(rows) {
  if (typeof Chart === 'undefined') return;
  const css = getComputedStyle(document.documentElement);
  const labels = rows.map((r) => new Date(r.tanggal).toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric' }));
  const data = {
    labels,
    datasets: [
      { type: 'bar', label: 'Pakan keluar (g)', data: rows.map((r) => r.pakan_g), backgroundColor: css.getPropertyValue('--accent').trim(), yAxisID: 'y', borderRadius: 4 },
      { type: 'line', label: 'Ditahan (kali)', data: rows.map((r) => r.tahan), borderColor: css.getPropertyValue('--warn').trim(), backgroundColor: css.getPropertyValue('--warn').trim(), yAxisID: 'y1', tension: 0.3 },
    ],
  };
  if (chart) { chart.data = data; chart.update(); return; }
  Chart.defaults.color = css.getPropertyValue('--muted').trim();
  chart = new Chart($('chart'), {
    data,
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: 'gram' } },
        y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { precision: 0 }, title: { display: true, text: 'kali' } },
      },
    },
  });
}

function pickFile(f) {
  if (!f) return;
  if (!f.type.startsWith('image/')) { showSimError('File harus berupa gambar.'); return; }
  file = f;
  $('preview').src = URL.createObjectURL(f);
  $('preview').hidden = false;
  $('dropText').hidden = true;
  $('send').disabled = false;
  $('simErr').hidden = true;
}

function showSimError(m) {
  $('simErr').textContent = m;
  $('simErr').hidden = false;
}

function showResult(r) {
  const beri = r.keputusan === 'BERI PAKAN';
  const dec = $('decision');
  dec.className = 'decision ' + (beri ? 'beri' : 'tahan');
  dec.textContent = `${r.keputusan} · ${r.alasan}`;

  $('probs').replaceChildren(...Object.entries(r.probabilitas).sort((a, b) => b[1] - a[1]).map(([k, v]) => el('div', { class: 'prob' },
    el('span', {}, k),
    (() => { const b = el('div', { class: 'bar' }, el('span', {})); b.firstElementChild.style.width = v * 100 + '%'; return b; })(),
    el('span', {}, pct(v)),
  )));

  const rows = [
    ['Hasil', `${r.label} (${pct(r.confidence)})`],
    ['Model', r.model],
    ['Ambang τ', num(r.tau)],
    ['Waktu proses', `${num(r.waktu_ms)} ms`],
    ['Efek ke tabung', r.pakan_keluar_g ? `−${fmtG(r.pakan_keluar_g)}, sisa ${fmtG(r.stok.sisa_g)} (${num(r.stok.persen)}%)` : 'Tidak ada pakan keluar'],
  ];
  $('detail').replaceChildren(...rows.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]));
  $('result').hidden = false;
}

const drop = $('drop');
$('file').addEventListener('change', (e) => pickFile(e.target.files[0]));
drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); pickFile(e.dataTransfer.files[0]); });

$('send').addEventListener('click', async () => {
  if (!file) { showSimError('Pilih foto terlebih dahulu.'); return; }
  const btn = $('send');
  btn.disabled = true;
  btn.textContent = 'Memproses…';
  $('simErr').hidden = true;
  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('code', code);
    showResult(await api('/api/predict', { method: 'POST', body: fd }));
    await load();
  } catch (e) {
    showSimError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Kirim ke alat';
  }
});

$('refill').addEventListener('click', async () => {
  try {
    await api('/api/refill', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    await load();
  } catch (e) {
    showSimError(e.message);
  }
});

load();
