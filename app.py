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

def download_job(job_id, url):
    jobs[job_id]["status"] = "downloading"
    output_path = DOWNLOAD_FOLDER / f"{job_id}.%(ext)s"
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
        "--output", str(output_path),
        "--no-playlist",
        "--print", "after_move:filepath",
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = result.stderr[-500:] if result.stderr else "Erreur inconnue"
            return

        # Trouver le fichier mp3 créé
        mp3_files = list(DOWNLOAD_FOLDER.glob(f"{job_id}.mp3"))
        if not mp3_files:
            # Essayer de trouver n'importe quel fichier avec cet id
            files = list(DOWNLOAD_FOLDER.glob(f"{job_id}.*"))
            if not files:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = "Fichier MP3 introuvable après conversion"
                return
            mp3_files = files

        jobs[job_id]["filepath"] = str(mp3_files[0])
        jobs[job_id]["filename"] = mp3_files[0].name
        jobs[job_id]["status"] = "done"

    except subprocess.TimeoutExpired:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = "Timeout — vidéo trop longue ou connexion lente"
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>YouTube → MP3</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', sans-serif;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .card {
    background: rgba(255,255,255,0.05);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 24px;
    padding: 48px 40px;
    width: 100%;
    max-width: 560px;
    box-shadow: 0 32px 64px rgba(0,0,0,0.4);
  }
  .logo { font-size: 48px; margin-bottom: 8px; text-align: center; }
  h1 {
    color: #fff;
    font-size: 1.8rem;
    text-align: center;
    margin-bottom: 6px;
    font-weight: 700;
  }
  .subtitle {
    color: rgba(255,255,255,0.5);
    text-align: center;
    font-size: 0.9rem;
    margin-bottom: 36px;
  }
  .input-group {
    display: flex;
    gap: 10px;
    margin-bottom: 24px;
  }
  input[type=text] {
    flex: 1;
    padding: 14px 18px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.08);
    color: #fff;
    font-size: 0.95rem;
    outline: none;
    transition: border 0.2s;
  }
  input[type=text]::placeholder { color: rgba(255,255,255,0.35); }
  input[type=text]:focus { border-color: #ff4e6a; }
  button.btn-convert {
    padding: 14px 22px;
    background: linear-gradient(135deg, #ff4e6a, #ff6b35);
    border: none;
    border-radius: 12px;
    color: #fff;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    white-space: nowrap;
  }
  button.btn-convert:hover { opacity: 0.9; transform: translateY(-1px); }
  button.btn-convert:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

  /* Progress */
  .progress-box {
    display: none;
    background: rgba(255,255,255,0.05);
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 20px;
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
    height: 8px;
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
    padding: 24px;
    background: rgba(0,255,120,0.07);
    border: 1px solid rgba(0,255,120,0.2);
    border-radius: 14px;
    margin-bottom: 20px;
  }
  .result-box .check { font-size: 40px; margin-bottom: 8px; }
  .result-box p { color: rgba(255,255,255,0.7); font-size: 0.85rem; margin-bottom: 16px; }
  .result-box .filename {
    color: #fff;
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 16px;
    word-break: break-all;
  }
  .btn-download {
    display: inline-block;
    padding: 12px 28px;
    background: linear-gradient(135deg, #00c853, #00e676);
    border-radius: 10px;
    color: #fff;
    font-weight: 700;
    text-decoration: none;
    font-size: 0.95rem;
    transition: opacity 0.2s;
  }
  .btn-download:hover { opacity: 0.85; }

  /* Error */
  .error-box {
    display: none;
    background: rgba(255,70,70,0.1);
    border: 1px solid rgba(255,70,70,0.3);
    border-radius: 14px;
    padding: 16px 20px;
    color: #ff8080;
    font-size: 0.85rem;
    margin-bottom: 20px;
  }

  .footer {
    text-align: center;
    color: rgba(255,255,255,0.25);
    font-size: 0.75rem;
    margin-top: 28px;
  }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🎵</div>
  <h1>YouTube → MP3</h1>
  <p class="subtitle">Colle un lien YouTube et télécharge en MP3</p>

  <div class="input-group">
    <input type="text" id="urlInput" placeholder="https://youtube.com/watch?v=..." />
    <button class="btn-convert" id="convertBtn" onclick="startConvert()">Convertir</button>
  </div>

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
  </div>

  <div class="footer">Usage personnel uniquement · qualité 192kbps</div>
</div>

<script>
let pollInterval = null;

function startConvert() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) { showError("Colle un lien YouTube d'abord !"); return; }

  hideAll();
  setLoading(true);
  showProgress();

  fetch('/api/convert', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url})
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) { showError(data.error); setLoading(false); return; }
    pollStatus(data.job_id);
  })
  .catch(() => { showError("Erreur réseau"); setLoading(false); });
}

function pollStatus(jobId) {
  let dots = 0;
  const statuses = ["Téléchargement", "Conversion en cours", "Finalisation"];
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
    .catch(() => { /* ignore réseau temporaire */ });
  }, 1500);
}

function showProgress() {
  document.getElementById('progressBox').style.display = 'block';
  document.getElementById('progressBar').style.width = '10%';
  document.getElementById('statusText').textContent = 'Démarrage...';
  document.getElementById('pct').textContent = '10%';
}

function showResult(jobId, filename) {
  document.getElementById('progressBox').style.display = 'none';
  const rb = document.getElementById('resultBox');
  rb.style.display = 'block';
  document.getElementById('filenameLabel').textContent = filename;
  document.getElementById('downloadLink').href = `/api/download/${jobId}`;
}

function showError(msg) {
  const eb = document.getElementById('errorBox');
  eb.style.display = 'block';
  eb.textContent = '❌ ' + msg;
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
  btn.textContent = loading ? '⏳ ...' : 'Convertir';
}

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


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "URL manquante"}), 400
    if "youtube.com" not in url and "youtu.be" not in url:
        return jsonify({"error": "Lien YouTube invalide"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "pending", "filepath": None, "filename": None, "error": None}

    t = threading.Thread(target=download_job, args=(job_id, url), daemon=True)
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
