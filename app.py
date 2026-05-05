# -*- coding: utf-8 -*-
import os
import re
import threading
import uuid
import time
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string, abort

app = Flask(__name__)

DOWNLOAD_FOLDER = Path("downloads")
DOWNLOAD_FOLDER.mkdir(exist_ok=True)

COOKIES_FILE = Path("youtube_cookies.txt")

def setup_cookies():
    """Decode les cookies depuis la variable d'environnement et les sauvegarde."""
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if cookies_b64:
        import base64
        try:
            cookies_data = base64.b64decode(cookies_b64).decode("utf-8")
            COOKIES_FILE.write_text(cookies_data, encoding="utf-8")
            print("[OK] Cookies YouTube charges depuis l'environnement.")
        except Exception as e:
            print(f"[WARN] Impossible de charger les cookies: {e}")

setup_cookies()

# Stocke les jobs en mémoire: {job_id: {status, filename, error, progress}}
jobs = {}

def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def get_ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def get_node_path():
    import shutil, platform
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\nodejs\node.exe",
            r"C:\Program Files (x86)\nodejs\node.exe",
        ]
        for p in candidates:
            if Path(p).exists():
                return p
    # Linux / Render
    found = shutil.which("node") or shutil.which("nodejs")
    return found or "node"

def time_to_seconds(t):
    """Convertit MM:SS ou HH:MM:SS en secondes."""
    if not t:
        return None
    parts = t.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        return None
    return None

def download_job(job_id, url, start_time=None, end_time=None):
    jobs[job_id]["status"] = "downloading"
    # Dossier par job pour eviter les conflits de noms
    output_dir = DOWNLOAD_FOLDER / job_id
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "%(title)s.%(ext)s"
    ffmpeg_path = get_ffmpeg_path()
    node_path = get_node_path()

    import subprocess, sys
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "--ffmpeg-location", ffmpeg_path,
        "--js-runtimes", f"node:{node_path}",
        "--extractor-args", "youtube:player_client=android,tv_embedded",
        "--user-agent", "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
        "--add-header", "Accept-Language:fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "--no-check-certificates",
        *(["--cookies", str(COOKIES_FILE)] if COOKIES_FILE.exists() else []),
        "--output", str(output_path),
        "--no-playlist",
        "--print", "after_move:filepath",
    ]

    # Ajout du trim si start/end fournis
    start_sec = time_to_seconds(start_time)
    end_sec   = time_to_seconds(end_time)
    if start_sec is not None or end_sec is not None:
        s = start_sec if start_sec is not None else 0
        e = end_sec   if end_sec   is not None else 99999
        cmd += ["--download-sections", f"*{s}-{e}", "--force-keyframes-at-cuts"]

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = result.stderr[-500:] if result.stderr else "Erreur inconnue"
            return

        # Chercher le MP3 dans le dossier du job
        mp3_files = list(output_dir.glob("*.mp3"))
        if not mp3_files:
            files = list(output_dir.glob("*.*"))
            if not files:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = "Fichier MP3 introuvable apres conversion"
                return
            mp3_files = files

        mp3_file = mp3_files[0]
        jobs[job_id]["filepath"] = str(mp3_file)
        jobs[job_id]["filename"] = mp3_file.name  # Ex: "Rick Astley - Never Gonna Give You Up.mp3"
        jobs[job_id]["status"] = "done"

    except subprocess.TimeoutExpired:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = "Timeout — video trop longue ou connexion lente"
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
<meta name="apple-mobile-web-app-title" content="YT MP3"/>
<meta name="theme-color" content="#0f0c29"/>
<link rel="manifest" href="/manifest.json"/>
<link rel="apple-touch-icon" href="/icon-192.png"/>
<title>YouTube → MP3</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    min-height: 100vh;
    min-height: -webkit-fill-available;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .card {
    background: rgba(255,255,255,0.05);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 24px;
    padding: 36px 24px;
    width: 100%;
    max-width: 560px;
    box-shadow: 0 32px 64px rgba(0,0,0,0.4);
  }
  .logo { font-size: 52px; margin-bottom: 8px; text-align: center; }
  h1 {
    color: #fff;
    font-size: 1.6rem;
    text-align: center;
    margin-bottom: 6px;
    font-weight: 700;
  }
  .subtitle {
    color: rgba(255,255,255,0.5);
    text-align: center;
    font-size: 0.88rem;
    margin-bottom: 28px;
    line-height: 1.4;
  }

  /* Sur mobile : input + bouton en colonne */
  .input-group {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 20px;
  }
  @media (min-width: 480px) {
    .input-group { flex-direction: row; }
  }

  input[type=text] {
    flex: 1;
    padding: 16px 18px;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.08);
    color: #fff;
    font-size: 16px; /* 16px minimum pour éviter le zoom auto iOS */
    outline: none;
    transition: border 0.2s;
    -webkit-appearance: none;
  }
  input[type=text]::placeholder { color: rgba(255,255,255,0.35); }
  input[type=text]:focus { border-color: #ff4e6a; }

  button.btn-convert {
    width: 100%;
    padding: 16px 22px;
    background: linear-gradient(135deg, #ff4e6a, #ff6b35);
    border: none;
    border-radius: 14px;
    color: #fff;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    -webkit-appearance: none;
    touch-action: manipulation;
    min-height: 52px;
  }
  @media (min-width: 480px) {
    button.btn-convert { width: auto; }
  }
  button.btn-convert:active { opacity: 0.8; transform: scale(0.98); }
  button.btn-convert:disabled { opacity: 0.5; }

  /* Bouton coller depuis presse-papier (mobile) */
  .btn-paste {
    width: 100%;
    padding: 12px;
    background: rgba(255,255,255,0.07);
    border: 1px dashed rgba(255,255,255,0.2);
    border-radius: 12px;
    color: rgba(255,255,255,0.6);
    font-size: 0.88rem;
    cursor: pointer;
    margin-bottom: 20px;
    touch-action: manipulation;
    -webkit-appearance: none;
  }
  .btn-paste:active { background: rgba(255,255,255,0.12); }

  /* Progress */
  .progress-box {
    display: none;
    background: rgba(255,255,255,0.05);
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 16px;
    border: 1px solid rgba(255,255,255,0.1);
  }
  .progress-label {
    color: rgba(255,255,255,0.7);
    font-size: 0.85rem;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
  }
  .progress-bar-wrap {
    background: rgba(255,255,255,0.1);
    border-radius: 8px;
    height: 10px;
    overflow: hidden;
  }
  .progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #ff4e6a, #ff6b35);
    border-radius: 8px;
    width: 0%;
    transition: width 0.4s;
    animation: pulse 1.5s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.7} }

  /* Result */
  .result-box {
    display: none;
    text-align: center;
    padding: 24px 16px;
    background: rgba(0,255,120,0.07);
    border: 1px solid rgba(0,255,120,0.2);
    border-radius: 14px;
    margin-bottom: 16px;
  }
  .result-box .check { font-size: 44px; margin-bottom: 8px; }
  .result-box p { color: rgba(255,255,255,0.7); font-size: 0.85rem; margin-bottom: 16px; }
  .result-box .filename {
    color: #fff;
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 16px;
    word-break: break-all;
  }
  .btn-download {
    display: block;
    width: 100%;
    padding: 16px 28px;
    background: linear-gradient(135deg, #00c853, #00e676);
    border-radius: 14px;
    color: #fff;
    font-weight: 700;
    text-decoration: none;
    font-size: 1rem;
    touch-action: manipulation;
    min-height: 52px;
    line-height: 1.2;
  }
  .btn-download:active { opacity: 0.85; }

  /* Note iPhone */
  .iphone-note {
    display: none;
    margin-top: 10px;
    padding: 10px 14px;
    background: rgba(255,200,0,0.1);
    border: 1px solid rgba(255,200,0,0.3);
    border-radius: 10px;
    color: rgba(255,220,100,0.9);
    font-size: 0.78rem;
    line-height: 1.5;
    text-align: left;
  }

  /* Trim section */
  .trim-toggle {
    width: 100%;
    padding: 11px 16px;
    background: rgba(255,255,255,0.05);
    border: 1px dashed rgba(255,255,255,0.18);
    border-radius: 12px;
    color: rgba(255,255,255,0.55);
    font-size: 0.88rem;
    cursor: pointer;
    margin-bottom: 16px;
    text-align: left;
    -webkit-appearance: none;
    touch-action: manipulation;
  }
  .trim-toggle:active { background: rgba(255,255,255,0.1); }
  .trim-box {
    display: none;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
  }
  .trim-box label {
    color: rgba(255,255,255,0.6);
    font-size: 0.8rem;
    display: block;
    margin-bottom: 5px;
  }
  .trim-row { display: flex; gap: 12px; }
  .trim-row > div { flex: 1; }
  .trim-box input[type=text] {
    width: 100%;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.08);
    color: #fff;
    font-size: 16px;
    outline: none;
  }
  .trim-box input[type=text]:focus { border-color: #ff4e6a; }
  .trim-hint {
    color: rgba(255,255,255,0.3);
    font-size: 0.75rem;
    margin-top: 10px;
    text-align: center;
  }

  /* Bouton installer PWA */
  .btn-install {
    display: none;
    width: 100%;
    padding: 13px;
    background: linear-gradient(135deg, #6c63ff, #a855f7);
    border: none;
    border-radius: 12px;
    color: #fff;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    margin-bottom: 14px;
    touch-action: manipulation;
    -webkit-appearance: none;
  }
  .btn-install:active { opacity: 0.85; }

  /* Error */
  .error-box {
    display: none;
    background: rgba(255,70,70,0.1);
    border: 1px solid rgba(255,70,70,0.3);
    border-radius: 14px;
    padding: 16px 20px;
    color: #ff8080;
    font-size: 0.85rem;
    margin-bottom: 16px;
  }

  .footer {
    text-align: center;
    color: rgba(255,255,255,0.2);
    font-size: 0.72rem;
    margin-top: 24px;
    line-height: 1.6;
  }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🎵</div>
  <h1>YouTube → MP3</h1>
  <p class="subtitle">Colle un lien YouTube et télécharge en MP3</p>

  <div class="input-group">
    <input type="text" id="urlInput" placeholder="https://youtube.com/watch?v=..." autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"/>
    <button class="btn-convert" id="convertBtn" onclick="startConvert()">Convertir</button>
  </div>

  <button class="btn-paste" onclick="pasteFromClipboard()">📋 Coller le lien depuis le presse-papier</button>

  <!-- Trim -->
  <button class="trim-toggle" id="trimToggle" onclick="toggleTrim()">✂️ Couper une partie (optionnel)</button>
  <div class="trim-box" id="trimBox">
    <div class="trim-row">
      <div>
        <label>Debut (MM:SS)</label>
        <input type="text" id="startTime" placeholder="0:00" maxlength="8"/>
      </div>
      <div>
        <label>Fin (MM:SS)</label>
        <input type="text" id="endTime" placeholder="3:30" maxlength="8"/>
      </div>
    </div>
    <p class="trim-hint">Exemple : debut 1:30 → fin 4:00 pour extraire 2m30s</p>
  </div>

  <!-- Bouton installer PWA -->
  <button class="btn-install" id="installBtn" onclick="installPWA()">📲 Installer l'app sur cet appareil</button>

  <div class="progress-box" id="progressBox">
    <div class="progress-label">
      <span id="statusText">Téléchargement en cours...</span>
      <span id="pct">–</span>
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar" id="progressBar"></div>
    </div>
  </div>

  <div class="error-box" id="errorBox"></div>

  <div class="result-box" id="resultBox">
    <div class="check">✅</div>
    <div class="filename" id="filenameLabel"></div>
    <p>Ton fichier MP3 est prêt !</p>
    <a id="downloadLink" class="btn-download" href="#">⬇️ Télécharger MP3</a>
    <div class="iphone-note" id="iphoneNote">
      💡 <strong>Sur iPhone :</strong> appuie sur le bouton, puis choisis
      "Télécharger le fichier lié" pour le sauvegarder dans Fichiers.
    </div>
  </div>

  <div class="footer">Usage personnel uniquement · qualité 192kbps<br>Fonctionne sur iPhone, Android et PC</div>
</div>

<script>
let pollInterval = null;
let deferredInstallPrompt = null;

// PWA : enregistrement du service worker
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// PWA : capturer l'evenement d'installation
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredInstallPrompt = e;
  document.getElementById('installBtn').style.display = 'block';
});
window.addEventListener('appinstalled', () => {
  document.getElementById('installBtn').style.display = 'none';
});

function installPWA() {
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then(() => {
      deferredInstallPrompt = null;
      document.getElementById('installBtn').style.display = 'none';
    });
  }
}

// Detecter iPhone/iOS
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
if (isIOS) {
  document.getElementById('iphoneNote') && (document.getElementById('iphoneNote').style.display = 'block');
  // Sur iOS, afficher un message d'installation specifique (pas de beforeinstallprompt)
  const installed = window.navigator.standalone;
  if (!installed) {
    const btn = document.getElementById('installBtn');
    btn.style.display = 'block';
    btn.textContent = `📲 Installer : appuie sur ⬆️ puis "Sur l'ecran d'accueil"`;
    btn.onclick = null;
  }
}

function toggleTrim() {
  const box = document.getElementById('trimBox');
  const btn = document.getElementById('trimToggle');
  const open = box.style.display === 'block';
  box.style.display = open ? 'none' : 'block';
  btn.textContent = open ? '✂️ Couper une partie (optionnel)' : '✂️ Masquer les options de coupe';
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      document.getElementById('urlInput').value = text;
      if (text.includes('youtube.com') || text.includes('youtu.be')) {
        startConvert();
      }
    }
  } catch(e) {
    document.getElementById('urlInput').focus();
    document.getElementById('urlInput').select();
  }
}

function startConvert() {
  const url   = document.getElementById('urlInput').value.trim();
  const start = document.getElementById('startTime').value.trim();
  const end   = document.getElementById('endTime').value.trim();

  if (!url) { showError("Colle un lien YouTube d'abord !"); return; }
  if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
    showError("Ce lien ne semble pas etre un lien YouTube valide.");
    return;
  }

  hideAll();
  setLoading(true);
  showProgress(start, end);

  fetch('/api/convert', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, start, end})
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) { showError(data.error); setLoading(false); return; }
    pollStatus(data.job_id);
  })
  .catch(() => { showError("Erreur réseau, réessaie dans quelques secondes."); setLoading(false); });
}

function pollStatus(jobId) {
  let dots = 0;
  const statuses = ["Telechargement", "Conversion en cours", "Finalisation"];
  let si = 0;
  let barW = 10;

  pollInterval = setInterval(() => {
    fetch(`/api/status/${jobId}`)
    .then(r => r.json())
    .then(data => {
      dots = (dots + 1) % 4;
      const dot = '.'.repeat(dots + 1);

      if (data.status === 'downloading') {
        si = Math.min(si + 1, statuses.length - 1);
        barW = Math.min(barW + 5, 85);
        document.getElementById('statusText').textContent = statuses[si] + dot;
        document.getElementById('progressBar').style.width = barW + '%';
        document.getElementById('pct').textContent = barW + '%';
      }
      else if (data.status === 'done') {
        clearInterval(pollInterval);
        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('pct').textContent = '100%';
        setTimeout(() => {
          showResult(jobId, data.filename);
          setLoading(false);
        }, 400);
      }
      else if (data.status === 'error') {
        clearInterval(pollInterval);
        showError(data.error || "Erreur lors de la conversion");
        setLoading(false);
      }
    })
    .catch(() => { /* ignore reseau temporaire */ });
  }, 1500);
}

function showProgress(start, end) {
  document.getElementById('progressBox').style.display = 'block';
  document.getElementById('progressBar').style.width = '10%';
  let label = 'Demarrage...';
  if (start || end) label = `Extraction ${start||'debut'} → ${end||'fin'}...`;
  document.getElementById('statusText').textContent = label;
  document.getElementById('pct').textContent = '10%';
}

function showResult(jobId, filename) {
  document.getElementById('progressBox').style.display = 'none';
  const rb = document.getElementById('resultBox');
  rb.style.display = 'block';
  document.getElementById('filenameLabel').textContent = filename;
  const link = document.getElementById('downloadLink');
  link.href = `/api/download/${jobId}`;
  // Sur iOS, afficher la note
  if (isIOS) {
    document.getElementById('iphoneNote').style.display = 'block';
  }
}

function showError(msg) {
  const eb = document.getElementById('errorBox');
  eb.style.display = 'block';
  eb.textContent = 'Erreur : ' + msg;
  document.getElementById('progressBox').style.display = 'none';
}

function hideAll() {
  document.getElementById('progressBox').style.display = 'none';
  document.getElementById('errorBox').style.display = 'none';
  document.getElementById('resultBox').style.display = 'none';
}

function setLoading(loading) {
  const btn = document.getElementById('convertBtn');
  btn.disabled = loading;
  btn.textContent = loading ? 'Conversion...' : 'Convertir';
}

// Soumettre avec Entree
document.getElementById('urlInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') startConvert();
});

document.getElementById('urlInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') startConvert();
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/manifest.json")
def manifest():
    from flask import Response
    data = {
        "name": "YouTube MP3",
        "short_name": "YT→MP3",
        "description": "Convertit des liens YouTube en MP3",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f0c29",
        "theme_color": "#0f0c29",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    import json
    return Response(json.dumps(data), mimetype="application/json")


@app.route("/icon-<size>.png")
def icon(size):
    """Génère une icône PNG simple via SVG→PNG avec pillow ou retourne un SVG encodé."""
    from flask import Response
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 100 100'>
  <rect width='100' height='100' rx='20' fill='#302b63'/>
  <text x='50' y='68' font-size='55' text-anchor='middle' fill='white'>&#127925;</text>
</svg>"""
    # Essayer de convertir en PNG avec cairosvg ou pillow
    try:
        import cairosvg
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(size), output_height=int(size))
        return Response(png, mimetype="image/png")
    except Exception:
        # Fallback : retourner le SVG
        return Response(svg, mimetype="image/svg+xml")


@app.route("/sw.js")
def service_worker():
    from flask import Response
    sw = """
const CACHE = 'yt-mp3-v1';
const ASSETS = ['/'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
"""
    return Response(sw, mimetype="application/javascript")


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.get_json()
    url        = (data or {}).get("url", "").strip()
    start_time = (data or {}).get("start", "").strip() or None
    end_time   = (data or {}).get("end",   "").strip() or None

    if not url:
        return jsonify({"error": "URL manquante"}), 400
    if "youtube.com" not in url and "youtu.be" not in url:
        return jsonify({"error": "Lien YouTube invalide"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "pending", "filepath": None, "filename": None, "error": None}

    t = threading.Thread(target=download_job, args=(job_id, url, start_time, end_time), daemon=True)
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    return jsonify({
        "status": job["status"],
        "filename": job.get("filename"),
        "error": job.get("error"),
    })


@app.route("/api/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        abort(404)
    filepath = job["filepath"]
    if not filepath or not Path(filepath).exists():
        abort(404)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=job["filename"],
        mimetype="audio/mpeg"
    )


if __name__ == "__main__":
    import socket
    port = int(os.environ.get("PORT", 5001))
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "localhost"
    print(f"\n[OK] Serveur demarre !")
    print(f"   Local  : http://localhost:{port}")
    print(f"   Reseau : http://{local_ip}:{port}  <- partage avec un ami sur le meme Wi-Fi\n")
    app.run(host="0.0.0.0", port=port, debug=False)
