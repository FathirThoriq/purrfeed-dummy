const code = new URLSearchParams(location.search).get('code');
if (!code) location.href = '/';

const $ = (id) => document.getElementById(id);
const num = (x, digits = 1) => Number(x).toLocaleString('id-ID', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
const pct = (p) => (p >= 0.9995 ? '> 99,9%' : p > 0 && p < 0.0005 ? '< 0,1%' : `${num(p * 100)}%`);
const icons = () => { if (window.lucide) lucide.createIcons(); };
icons();
window.addEventListener('pf-theme', drawCharts);

let DATA = null, SOURCE = 'all', lastN = 0, uploadURL = null;

function el(tag, cls, ...children) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(c ?? ''));
  return n;
}
function icon(name, size = 16) {
  const i = document.createElement('i');
  i.setAttribute('data-lucide', name); i.setAttribute('width', size); i.setAttribute('height', size);
  requestAnimationFrame(() => icons());
  return i;
}
function toast(text, bad = false) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const t = el('div', 'toast' + (bad ? ' bad' : ''), icon(bad ? 'triangle-alert' : 'check'), text);
  document.body.append(t); icons();
  setTimeout(() => t.remove(), 3200);
}

async function api(path, options) {
  const r = await fetch(path, options);
  const j = await r.json().catch(() => ({ error: 'Respons server tidak valid.' }));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* ---------- fetch + render ---------- */
async function load() {
  try {
    DATA = await api('/api/dashboard?code=' + encodeURIComponent(code));
    render();
  } catch (e) { toast(e.message, true); }
}

function render() {
  const { device, stok, ringkasan } = DATA;
  $('devCode').textContent = device.code;
  $('devPet').textContent = device.hewan;
  $('petIcon').replaceChildren(icon(device.mode === 'anjing' ? 'dog' : 'cat', 18));
  $('petStatIcon').setAttribute('data-lucide', device.mode === 'anjing' ? 'dog' : 'cat');
  $('petStatLabel').textContent = device.hewan + ' terdeteksi';

  $('sisa').innerHTML = '';
  $('sisa').append(`${num(stok.sisa_g)} `, el('small', '', 'g'));
  $('sisaBar').style.width = Math.min(100, stok.persen) + '%';
  $('sisaSub').textContent = stok.perkiraan_habis_hari == null
    ? `${num(stok.persen)}% dari ${num(stok.kapasitas_g)} g`
    : `${num(stok.persen)}% dari ${num(stok.kapasitas_g)} g · habis ±${num(stok.perkiraan_habis_hari, 0)} hari`;
  $('rasio').textContent = ringkasan.rasio_terbuang == null ? '-' : num(ringkasan.rasio_terbuang) + '%';
  $('rasioSub').textContent = ringkasan.rasio_terbuang == null ? 'belum ada data dari alat'
    : `${num(ringkasan.pakan_terbuang_g)} g dari ${num(ringkasan.pakan_keluar_g)} g`;
  $('total').textContent = ringkasan.total;
  $('hewan').textContent = ringkasan.hewan;
  $('bukan').textContent = ringkasan.bukan;

  if (!device.model_tersedia) toast(device.model_masalah ? `Model ${device.hewan} ditolak: ${device.model_masalah}` : `Model ${device.hewan} belum diunggah.`, true);

  drawCharts();
  renderHistory();
  renderTips();
  icons();
}

/* ---------- hasil klasifikasi ---------- */
function resultHTML(target, title) {
  target.innerHTML = '';
  target.append(el('p', 'resultEmpty', title || 'Hasil tampil di sini.'));
}
function renderResult(target, r) {
  target.innerHTML = '';
  target.classList.remove('fade'); void target.offsetWidth; target.classList.add('fade');
  const verdict = el('div', 'verdict',
    el('div', 'icon', icon(r.kelas === 'Bukan Keduanya' ? 'ban' : (r.mode === 'anjing' ? 'dog' : 'cat'), 32)),
    el('div', '', el('div', 'kelas', r.kelas), el('div', 'conf', `Confidence ${pct(r.confidence)} · ${({ upload: 'Upload', webcam: 'Webcam' })[r.sumber] || 'ESP32-CAM'}`)));
  target.append(verdict);
  target.append(el('h3', '', 'Hasil Klasifikasi'));
  const facts = el('dl', 'facts');
  for (const [k, v] of [
    ['Kelas', r.kelas], ['Confidence', pct(r.confidence)],
    ['Waktu proses', `${num(r.waktu_ms)} ms`], ['Tindakan servo', r.pakan_keluar_g ? `Beri pakan ${num(r.pakan_keluar_g)} g` : r.alasan],
  ]) { const row = el('div', ''); row.append(el('dt', '', k), el('dd', '', v)); facts.append(row); }
  target.append(facts);
}
resultHTML($('resultUpload'), 'Upload gambar lalu klasifikasi.');
resultHTML($('resultCam'), 'Hasil ESP32-CAM tampil di sini.');

/* ---------- grafik ---------- */
function drawCharts() {
  const rows = DATA.grafik;
  const labels = rows.map((r) => new Date(r.tanggal + 'T12:00').toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric' }));
  $('barChart').innerHTML = barSVG(rows, labels);
  $('lineChart').innerHTML = lineSVG(rows, labels);
  const vals = rows.map((r) => r.confidence).filter((v) => v != null);
  $('confAvg').textContent = vals.length ? num(vals.reduce((a, b) => a + b, 0) / vals.length) + '%' : '-';
}
function barSVG(rows, labels) {
  const W = 460, H = 190, padL = 40, padB = 28, padT = 12;
  const max = Math.max(10, ...rows.flatMap((r) => [r.keluar_g, r.terbuang_g]));
  const y = (v) => padT + (1 - v / max) * (H - padT - padB);
  const n = rows.length, slot = (W - padL) / n, bw = 26;
  const s = [`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pakan keluar dan terbuang per hari">`];
  for (let g = 0; g <= 3; g++) { const yy = padT + (H - padT - padB) * g / 3; s.push(`<line class="grid" x1="${padL}" y1="${yy}" x2="${W}" y2="${yy}"/>`); }
  rows.forEach((r, i) => {
    const x = padL + slot * i + slot / 2;
    if (r.keluar_g) s.push(`<rect class="barA" x="${x - bw / 2 - 14}" y="${y(r.keluar_g)}" width="18" height="${H - padB - y(r.keluar_g)}" rx="3"/>`);
    if (r.terbuang_g) s.push(`<rect class="barB" x="${x - bw / 2 + 10}" y="${y(r.terbuang_g)}" width="18" height="${H - padB - y(r.terbuang_g)}" rx="3"/>`);
    s.push(`<text x="${x}" y="${H - 8}" text-anchor="middle">${labels[i]}</text>`);
  });
  return s.join('') + '</svg>';
}
function lineSVG(rows, labels) {
  const W = 460, H = 190, padL = 40, padB = 28, padT = 28;
  const vals = rows.map((r) => r.confidence);
  const have = vals.filter((v) => v != null);
  if (!have.length) return '<p class="muted">Belum ada data confidence.</p>';
  let lo = Math.min(...have), hi = Math.max(...have);
  if (hi - lo < 5) { lo = Math.max(0, lo - 2.5); hi = Math.min(100, hi + 2.5); }
  else { lo = Math.max(0, lo - 1); hi = Math.min(100, hi + 1); }
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
  const x = (i) => padL + i * (W - padL - 10) / (rows.length - 1);
  const s = [`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Confidence rata-rata per hari">`];
  for (let g = 0; g <= 3; g++) {
    const yy = padT + (H - padT - padB) * g / 3, vv = hi - (hi - lo) * g / 3;
    s.push(`<line class="grid" x1="${padL}" y1="${yy}" x2="${W}" y2="${yy}"/><text x="${padL - 6}" y="${yy + 4}" text-anchor="end">${Math.round(vv)}%</text>`);
  }
  let path = '', pts = [];
  vals.forEach((v, i) => { if (v == null) return; path += (path ? 'L' : 'M') + `${x(i).toFixed(1)},${y(v).toFixed(1)}`; pts.push([x(i), y(v), v, i]); });
  s.push(`<path class="line" d="${path}"/>`);
  for (const [px, py, v, i] of pts) {
    s.push(`<circle class="dot" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="5"/><text class="val" x="${px.toFixed(1)}" y="${(py - 11).toFixed(1)}" text-anchor="middle">${Math.round(v)}%</text>`);
    s.push(`<text x="${px.toFixed(1)}" y="${H - 8}" text-anchor="middle">${labels[i]}</text>`);
  }
  return s.join('') + '</svg>';
}

/* ---------- riwayat ---------- */
const dayKey = (ts) => ts.slice(0, 10);
const hari = (key) => new Date(key + 'T12:00').toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'short' });
function renderHistory() {
  const rows = DATA.riwayat.filter((r) => SOURCE === 'all' || r.sumber === SOURCE);
  const host = $('hist');
  host.innerHTML = '';
  if (!rows.length) { host.append(el('p', 'emptyList', DATA.riwayat.length ? 'Tidak ada riwayat dari sumber ini.' : 'Belum ada klasifikasi. Upload gambar atau tunggu kiriman ESP32-CAM.')); return; }
  let lastDay = '';
  rows.forEach((r) => {
    if (dayKey(r.ts) !== lastDay) { lastDay = dayKey(r.ts); host.append(el('h3', '', hari(lastDay))); }
    host.append(historyItem(r));
  });
  icons();
}
function historyItem(r) {
  const when = el('div', 'when', r.ts.slice(11, 16), el('span', '', r.kelas || '-', el('span', 'tag', r.sumber_label)));
  const thumb = el('div', 'thumb');
  if (r.thumb) { const img = document.createElement('img'); img.src = r.thumb; img.alt = ''; thumb.append(img); }
  else thumb.append(icon(r.ikon || 'utensils', 24));
  const what = el('div', 'what', el('b', '', r.tindakan),
    el('span', '', (r.confidence != null ? `Confidence ${pct(r.confidence)}` : '') + (r.waktu_ms != null ? ` · ${num(r.waktu_ms, 0)} ms` : '')));
  const item = el('div', 'item', thumb, when, what);
  return item;
}

/* ---------- tabs upload / kamera ---------- */
const TABS = { upload: ['tabUpload', 'paneUpload'], webcam: ['tabWebcam', 'paneWebcam'], cam: ['tabCam', 'paneCam'] };
function selectTab(which) {
  for (const [name, [tab, pane]] of Object.entries(TABS)) {
    $(tab).setAttribute('aria-selected', name === which);
    $(pane).hidden = name !== which;
  }
  if (which === 'webcam') listCameras().catch(() => {}); else stopWebcam();
}
for (const name of Object.keys(TABS)) $(TABS[name][0]).addEventListener('click', () => selectTab(name));

function dropzoneActive(on) { $('dropzone').classList.toggle('live', on); }
['dragover', 'dragenter'].forEach((ev) => $('dropzone').addEventListener(ev, (e) => { e.preventDefault(); dropzoneActive(true); }));
['dragleave', 'drop'].forEach((ev) => $('dropzone').addEventListener(ev, (e) => { e.preventDefault(); dropzoneActive(false); }));
$('dropzone').addEventListener('drop', (e) => pick(e.dataTransfer.files[0]));
$('pick').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', (e) => pick(e.target.files[0]));
function pick(f) {
  if (!f) return;
  if (!f.type.startsWith('image/')) { toast('File harus berupa gambar.', true); return; }
  if (uploadURL) URL.revokeObjectURL(uploadURL);
  uploadURL = URL.createObjectURL(f);
  $('preview').src = uploadURL; $('preview').hidden = false; $('previewEmpty').hidden = true;
  $('classify').disabled = $('reset').disabled = false;
  $('pick').firstChild.textContent = ' ';
}
$('reset').addEventListener('click', () => {
  $('file').value = ''; $('preview').hidden = true; $('previewEmpty').hidden = false;
  $('classify').disabled = $('reset').disabled = true;
  resultHTML($('resultUpload'), 'Upload gambar lalu klasifikasi.');
});
$('classify').addEventListener('click', async () => {
  const f = $('file').files[0];
  if (!f) { toast('Pilih gambar dulu.', true); return; }
  const btn = $('classify'); btn.disabled = true;
  try {
    const fd = new FormData();
    fd.append('file', f); fd.append('code', code); fd.append('mode', DATA.device.mode); fd.append('source', 'upload');
    renderResult($('resultUpload'), await api('/api/predict', { method: 'POST', body: fd }));
    await load();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});

/* ---------- webcam USB (getUserMedia) + kotak deteksi ---------- */
const CAM_KEY = 'pf-webcam';
let camStream = null, camBusy = false, camTimer = null, lastBox = null;
resultHTML($('resultWebcam'), 'Nyalakan webcam, arahkan ke hewan.');

async function listCameras() {
  const sel = $('camSelect');
  const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput' && d.deviceId);
  if (!cams.length) {   // Firefox baru menampilkan daftar kamera setelah izin diberikan
    sel.replaceChildren(el('option', '', camStream ? 'Kamera aktif' : 'Klik Nyalakan untuk izin kamera'));
    sel.firstChild.value = '';
    return;
  }
  const current = camStream?.getVideoTracks()[0]?.getSettings().deviceId || localStorage.getItem(CAM_KEY) || '';
  sel.replaceChildren(...cams.map((d, i) => {
    const o = el('option', '', d.label || `Kamera ${i + 1}`); o.value = d.deviceId; o.selected = d.deviceId === current; return o;
  }));
}
async function startWebcam() {
  if (!navigator.mediaDevices?.getUserMedia) { toast('Browser tidak mengizinkan kamera (buka lewat localhost atau HTTPS).', true); return; }
  stopWebcam();
  const id = $('camSelect').value || localStorage.getItem(CAM_KEY);
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { ...(id ? { deviceId: { exact: id } } : {}), width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
  } catch (e) {
    if (id && e.name === 'OverconstrainedError') { localStorage.removeItem(CAM_KEY); $('camSelect').value = ''; return startWebcam(); }
    toast(e.name === 'NotReadableError' ? 'Kamera sedang dipakai aplikasi lain. Tutup aplikasinya lalu coba lagi.'
      : e.name === 'NotAllowedError' ? 'Izin kamera ditolak browser/sistem. Izinkan kamera untuk situs ini lalu muat ulang.'
      : e.name === 'NotFoundError' ? 'Kamera tidak ditemukan.' : `Kamera gagal dibuka: ${e.message}`, true);
    return;
  }
  const v = $('webcam');
  v.srcObject = camStream; v.hidden = false; $('webcamEmpty').hidden = true; $('webcamFrame').classList.add('live');
  $('camShot').disabled = false;
  $('camStart').replaceChildren(icon('power-off'), ' Matikan');
  await listCameras();
  const used = camStream.getVideoTracks()[0].getSettings().deviceId;
  if (used) localStorage.setItem(CAM_KEY, used);
  scheduleLive(300);
}
function stopWebcam() {
  clearTimeout(camTimer);
  if (!camStream) return;
  camStream.getTracks().forEach((t) => t.stop());
  camStream = null; lastBox = null;
  const v = $('webcam'); v.srcObject = null; v.hidden = true;
  $('webcamEmpty').hidden = false; $('webcamFrame').classList.remove('live');
  $('camShot').disabled = true;
  $('camStart').replaceChildren(icon('power'), ' Nyalakan');
  drawBox();
}
$('camStart').addEventListener('click', () => (camStream ? stopWebcam() : startWebcam()));
$('camSelect').addEventListener('change', () => { localStorage.setItem(CAM_KEY, $('camSelect').value); if (camStream) startWebcam(); });
$('camLive').addEventListener('change', () => { if ($('camLive').checked) scheduleLive(0); else { clearTimeout(camTimer); lastBox = null; drawBox(); } });

function grabFrame() {
  const v = $('webcam');
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  return new Promise((ok) => c.toBlob(ok, 'image/jpeg', 0.92));
}
async function classifyFrame(record) {
  const v = $('webcam');
  if (!camStream || !v.videoWidth || camBusy) return null;
  camBusy = true;
  try {
    const fd = new FormData();
    fd.append('file', await grabFrame(), 'webcam.jpg');
    fd.append('mode', DATA?.device.mode || 'kucing');
    if (record) { fd.append('code', code); fd.append('source', 'webcam'); } else fd.append('source', 'upload');
    const r = await api('/api/predict', { method: 'POST', body: fd });
    if (!camStream) return null;
    lastBox = r; drawBox(); renderResult($('resultWebcam'), { ...r, sumber: 'webcam' });
    return r;
  } finally { camBusy = false; }
}
function scheduleLive(ms) {
  clearTimeout(camTimer);
  if (!camStream || !$('camLive').checked) return;
  camTimer = setTimeout(async () => {
    try { await classifyFrame(false); } catch (e) { toast(e.message, true); }
    scheduleLive(700);
  }, ms);
}
$('camShot').addEventListener('click', async () => {
  const btn = $('camShot'); btn.disabled = true;
  try {
    while (camBusy) await new Promise((ok) => setTimeout(ok, 100));
    const r = await classifyFrame(true);
    if (r) { toast(r.pakan_keluar_g ? `Tercatat: beri pakan ${num(r.pakan_keluar_g)} g.` : `Tercatat: ${r.alasan}.`); await load(); }
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = !camStream; }
});

/* Kotak = area objek yang dipotong untuk model (hasil segmentasi), digambar di atas video. */
function drawBox() {
  const c = $('webcamBox'), v = $('webcam'), frame = $('webcamFrame');
  const dpr = window.devicePixelRatio || 1;
  c.width = frame.clientWidth * dpr; c.height = frame.clientHeight * dpr;
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, frame.clientWidth, frame.clientHeight);
  const r = lastBox;
  if (!r || !camStream || !v.videoWidth) return;
  const scale = Math.min(frame.clientWidth / v.videoWidth, frame.clientHeight / v.videoHeight);
  const w = v.videoWidth * scale, h = v.videoHeight * scale;
  const ox = (frame.clientWidth - w) / 2, oy = (frame.clientHeight - h) / 2;
  const [x0, y0, x1, y1] = r.kotak || [0, 0, 1, 1];
  const bx = ox + x0 * w, by = oy + y0 * h, bw = (x1 - x0) * w, bh = (y1 - y0) * h;
  const isTarget = r.label === r.mode;
  const color = r.keputusan === 'BERI PAKAN' ? '#8FD0C7' : isTarget ? '#E6C175' : '#F0A184';
  g.lineWidth = 3; g.strokeStyle = color; g.setLineDash(r.kotak ? [] : [8, 6]);
  g.strokeRect(bx + 1.5, by + 1.5, Math.max(bw - 3, 0), Math.max(bh - 3, 0));
  g.setLineDash([]);
  const text = `${r.kelas} ${pct(r.confidence)}${r.kotak ? '' : ' · seluruh frame'}`;
  g.font = '700 14px "Plus Jakarta Sans", sans-serif';
  const tw = g.measureText(text).width + 16, th = 26;
  const tx = Math.min(Math.max(bx, ox), ox + w - tw), ty = by - th >= oy ? by - th : by;
  g.fillStyle = color; g.fillRect(tx, ty, tw, th);
  g.fillStyle = '#031816'; g.textBaseline = 'middle'; g.fillText(text, tx + 8, ty + th / 2 + 1);
}
window.addEventListener('resize', drawBox);
$('webcam').addEventListener('loadedmetadata', drawBox);
navigator.mediaDevices?.addEventListener?.('devicechange', () => { if (camStream) listCameras(); });

/* ---------- kamera: polling ---------- */
async function poll() {
  try {
    const j = await api('/api/latest?code=' + encodeURIComponent(code));
    const st = $('camStatus');
    if (!j.ada) { st.className = 'status off'; st.replaceChildren(icon('wifi-off'), el('span', '', 'Menunggu alat')); return; }
    if (j.umur_s < 20) { st.className = 'status ok'; st.replaceChildren(icon('wifi'), el('span', '', 'Terhubung')); }
    else { st.className = 'status off'; st.replaceChildren(icon('wifi-off'), el('span', '', `Terputus ${Math.round(j.umur_s)} dtk`)); }
    if (j.n !== lastN) {
      lastN = j.n;
      $('cam').src = '/api/latest.jpg?code=' + encodeURIComponent(code) + '&n=' + j.n;
      $('cam').hidden = false; $('camEmpty').hidden = true; $('camFrame').classList.add('live');
      renderResult($('resultCam'), j.hasil);
      await load();
    }
  } catch { /* coba lagi */ }
}

/* ---------- filter + export ---------- */
$('filter').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  SOURCE = b.dataset.src;
  document.querySelectorAll('#filter button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  renderHistory();
});
const menu = $('exportMenu');
$('exportBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  menu.hidden = !menu.hidden;
  $('exportBtn').setAttribute('aria-expanded', !menu.hidden);
});
document.addEventListener('click', () => { menu.hidden = true; $('exportBtn').setAttribute('aria-expanded', 'false'); });
menu.addEventListener('click', async (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  menu.hidden = true;
  try {
    const r = await fetch(`/api/export?code=${encodeURIComponent(code)}&format=${b.dataset.format}`);
    if (!r.ok) throw new Error((await r.json()).error);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = `riwayat-purrfeed-7-hari.${b.dataset.format === 'xlsx' ? 'xlsx' : 'csv'}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast('Export selesai.');
  } catch (err) { toast(err.message, true); }
});

/* ---------- isi ulang ---------- */
$('refill').addEventListener('click', async () => {
  try {
    const j = await api('/api/refill', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    toast(`Tabung diisi, ditambah ${num(j.ditambahkan_g)} g.`);
    await load();
  } catch (e) { toast(e.message, true); }
});
/* ---------- purr assistant ---------- */
$('fab').addEventListener('click', () => {
  $('chat').hidden = false;
  showPending();
  $('msgs').scrollTop = 1e6; $('chatInput').focus();
});
$('chatClose').addEventListener('click', () => { $('chat').hidden = true; });
function renderTips() {
  const tips = $('tips'); tips.innerHTML = '';
  for (const s of DATA.saran) {
    const b = el('button', 'tip', icon(s.ikon, 15), s.teks);
    b.addEventListener('click', () => ask(s.tanya));
    tips.append(b);
  }
}
function bubble(text, me = false, extra = '') {
  const m = el('div', 'msg ' + (me ? 'me' : 'bot') + (extra ? ' ' + extra : ''), text);
  $('msgs').append(m); $('msgs').scrollTop = 1e6; icons();
  return m;
}
const GREETING = 'Meow! Aku Purr. Tanya soal sisa pakan, pakan terbuang, atau hasil terakhir.';
const turns = [];
const READ_KEY = 'pf-read-' + code;
const readIds = new Set(JSON.parse(localStorage.getItem(READ_KEY) || '[]'));
let pending = [];
bubble(GREETING);
async function ask(text) {
  bubble(text, true);
  const thinking = bubble('...');
  try {
    const j = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, pesan: text, riwayat: turns.slice(-6) }) });
    thinking.remove();
    turns.push({ role: 'user', content: text }, { role: 'assistant', content: j.teks });
    bubble(j.teks);
  } catch (e) { thinking.remove(); bubble(e.message); }
}
$('chatForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const v = $('chatInput').value.trim();
  if (!v) return;
  $('chatInput').value = '';
  ask(v);
});

/* ---------- inisiatif Purr: badge merah + pesan ---------- */
function setBadge() {
  const n = pending.length;
  $('badge').hidden = n === 0 || !$('chat').hidden;
  $('badge').textContent = n > 9 ? '9+' : n;
  $('fab').setAttribute('aria-label', n ? `Purr Assistant, ${n} pesan baru` : 'Purr Assistant');
}
function showPending() {
  const shown = new Set();
  for (const m of pending) {
    const lvl = m.level === 'mendesak' ? ' mendesak' : '';
    const b = bubble('', false, 'proaktif' + lvl);
    b.append(el('div', 'tagline', icon(m.level === 'saran' ? 'lightbulb' : 'triangle-alert', 14), m.level === 'saran' ? 'Saran Purr' : 'Perlu perhatian'), m.teks);
    turns.push({ role: 'assistant', content: m.teks });
    readIds.add(m.id); shown.add(m.id);
  }
  if (shown.size) localStorage.setItem(READ_KEY, JSON.stringify([...readIds].slice(-200)));
  pending = [];
  setBadge(); icons();
}
async function checkProactive() {
  try {
    const { pesan } = await api('/api/proaktif?code=' + encodeURIComponent(code));
    const fresh = pesan.filter((m) => !readIds.has(m.id));
    if (!$('chat').hidden) { pending = fresh; if (fresh.length) showPending(); return; }
    pending = fresh;
    setBadge();
  } catch { /* coba lagi 30 detik lagi */ }
}

/* ---------- bersihkan chat ---------- */
$('chatClear').addEventListener('click', () => {
  turns.length = 0;
  $('msgs').replaceChildren();
  bubble(GREETING);
  toast('Chat dibersihkan.');
});

load();
setInterval(poll, 2000);
poll();
checkProactive();
setInterval(checkProactive, 30000);
