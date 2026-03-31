#!/usr/bin/env python3
"""
server.py - Servidor web FaPi
Sirve la interfaz de gestión en http://<ip-rpi>:8000

Endpoints:
  GET  /                      → Interfaz web
  GET  /api/audios            → Lista de audios disponibles
  POST /api/upload            → Subir nuevo audio
  DELETE /api/audio/<nombre>  → Eliminar audio
  GET  /api/assignments       → Leer asignaciones NFC
  POST /api/save              → Guardar asignaciones NFC
  POST /api/nfc/scan/start    → Iniciar escucha del RC522
  POST /api/nfc/scan/stop     → Detener escucha
  GET  /api/nfc/scan/result   → Consultar si se ha leído un tag
"""

import os
import json
import tempfile
import threading
import time
import zipfile
import shutil
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# ── Configuración ────────────────────────────────────────────
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
AUDIOS_DIR       = os.path.join(BASE_DIR, "audios")
WEB_DIR          = os.path.join(BASE_DIR, "web")
ASSIGNMENTS_FILE = os.path.join(BASE_DIR, "assignments.json")
TEMP_DIR         = os.path.join(BASE_DIR, "tmp")
ALLOWED_EXT      = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_ZIP      = {"zip"}
PORT             = 8000

os.makedirs(AUDIOS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Redirigir archivos temporales a la SD en lugar de /tmp (RAM)
tempfile.tempdir = TEMP_DIR

app = Flask(__name__, static_folder=WEB_DIR)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB máximo

# ── Estado del escáner NFC ───────────────────────────────────
nfc_state = {
    "scanning": False,
    "result":   None,   # {"uid": "...", "already_assigned": bool, "audio": "..."}
    "thread":   None,
}
nfc_lock = threading.Lock()

# ── Helpers ──────────────────────────────────────────────────
def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def load_assignments():
    if os.path.exists(ASSIGNMENTS_FILE):
        with open(ASSIGNMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_assignments(data):
    with open(ASSIGNMENTS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def uid_to_hex(uid_int):
    """Convierte el UID entero del RC522 a formato AA:BB:CC:DD"""
    h = format(uid_int, '08X')
    return ':'.join(h[i:i+2] for i in range(0, len(h), 2)).lstrip('0:').lstrip('0') or '00'

def suprimir_salida():
    import os
    devnull    = os.open(os.devnull, os.O_WRONLY)
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    return old_stdout, old_stderr

def restaurar_salida(old_stdout, old_stderr):
    import os
    os.dup2(old_stdout, 1)
    os.dup2(old_stderr, 2)
    os.close(old_stdout)
    os.close(old_stderr)

def nfc_scan_worker():
    """Hilo que lee el RC522 hasta detectar un tag o que se pare."""
    try:
        from mfrc522 import SimpleMFRC522
        reader = SimpleMFRC522()
        rdr    = reader.READER
        while True:
            with nfc_lock:
                if not nfc_state["scanning"]:
                    break

            old = suprimir_salida()
            uid, _ = reader.read_no_block()
            try:
                rdr.MFRC522_StopCrypto1()
            except Exception:
                pass
            restaurar_salida(*old)

            if uid:
                uid_hex        = uid_to_hex(uid)
                assignments    = load_assignments()
                assigned_audio = assignments.get(uid_hex, "")
                with nfc_lock:
                    nfc_state["result"] = {
                        "uid":              uid_hex,
                        "already_assigned": bool(assigned_audio),
                        "audio":            assigned_audio,
                    }
                    nfc_state["scanning"] = False
                break
            time.sleep(0.2)
    except Exception as e:
        with nfc_lock:
            nfc_state["result"]   = {"error": str(e)}
            nfc_state["scanning"] = False

# ── Rutas ────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')

	
@app.route('/fonts/<path:filename>')
def fonts(filename):
    return send_from_directory(os.path.join(WEB_DIR, 'fonts'), filename)


@app.route('/api/audios', methods=['GET'])
def get_audios():
    files = []
    for f in sorted(os.listdir(AUDIOS_DIR)):
        if allowed(f):
            size = os.path.getsize(os.path.join(AUDIOS_DIR, f))
            files.append({"name": f, "size": size})
    return jsonify(files)

@app.route('/api/folders', methods=['GET'])
def get_folders():
    """Lista subcarpetas de audios (playlists)."""
    folders = []
    for name in sorted(os.listdir(AUDIOS_DIR)):
        path = os.path.join(AUDIOS_DIR, name)
        if os.path.isdir(path):
            tracks = sorted([
                f for f in os.listdir(path)
                if f.lower().rsplit('.', 1)[-1] in ALLOWED_EXT
            ])
            folders.append({"name": name, "tracks": tracks, "count": len(tracks)})
    return jsonify(folders)

@app.route('/api/upload_zip', methods=['POST'])
def upload_zip():
    """Sube un ZIP, extrae los audios compatibles y crea una subcarpeta."""
    if 'file' not in request.files:
        return jsonify({"error": "No se recibió archivo"}), 400
    file = request.files['file']
    if not file.filename.lower().endswith('.zip'):
        return jsonify({"error": "Solo se admiten archivos .zip"}), 400

    folder_name = secure_filename(file.filename[:-4])  # nombre sin .zip
    folder_path = os.path.join(AUDIOS_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    zip_tmp = os.path.join(TEMP_DIR, secure_filename(file.filename))
    file.save(zip_tmp)

    extracted = []
    rejected  = []
    try:
        with zipfile.ZipFile(zip_tmp, 'r') as z:
            for member in z.namelist():
                basename = os.path.basename(member)
                if not basename:
                    continue
                ext = basename.rsplit('.', 1)[-1].lower() if '.' in basename else ''
                if ext in ALLOWED_EXT:
                    safe_name = secure_filename(basename)
                    dest = os.path.join(folder_path, safe_name)
                    with z.open(member) as src, open(dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append(safe_name)
                else:
                    if basename:
                        rejected.append(basename)
    except zipfile.BadZipFile:
        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify({"error": "El archivo ZIP no es válido"}), 400
    finally:
        try:
            os.remove(zip_tmp)
        except Exception:
            pass

    if not extracted:
        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify({"error": "El ZIP no contenía audios compatibles"}), 400

    return jsonify({
        "folder": folder_name,
        "extracted": sorted(extracted),
        "rejected": rejected
    }), 201

@app.route('/api/folder/<foldername>', methods=['DELETE'])
def delete_folder(foldername):
    foldername = secure_filename(foldername)
    path = os.path.join(AUDIOS_DIR, foldername)
    if not os.path.isdir(path):
        return jsonify({"error": "Carpeta no encontrada"}), 404
    shutil.rmtree(path)
    # Limpiar asignaciones que apunten a esta carpeta
    assignments = load_assignments()
    assignments = {
        uid: val for uid, val in assignments.items()
        if not (isinstance(val, dict) and val.get("folder") == foldername)
    }
    save_assignments(assignments)
    return jsonify({"ok": True})

@app.route('/api/upload', methods=['POST'])

def upload_audio():
    if 'file' not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400
    if not allowed(file.filename):
        return jsonify({"error": "Formato no permitido. Usa MP3, WAV, OGG o M4A"}), 400

    filename = secure_filename(file.filename)
    dest = os.path.join(AUDIOS_DIR, filename)
    file.save(dest)
    for f in os.listdir(TEMP_DIR):
        try:
            os.remove(os.path.join(TEMP_DIR, f))
        except:
            pass
    size = os.path.getsize(dest)
    return jsonify({"name": filename, "size": size}), 201

@app.route('/api/audio/<filename>', methods=['DELETE'])
def delete_audio(filename):
    filename = secure_filename(filename)
    path = os.path.join(AUDIOS_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Archivo no encontrado"}), 404
    os.remove(path)
    assignments = load_assignments()
    assignments = {uid: aud for uid, aud in assignments.items() if aud != filename}
    save_assignments(assignments)
    return jsonify({"ok": True})

@app.route('/api/assignments', methods=['GET'])
def get_assignments():
    return jsonify(load_assignments())

@app.route('/api/save', methods=['POST'])
def save():
    data = request.get_json()
    if not data or 'assignments' not in data:
        return jsonify({"error": "Datos inválidos"}), 400
    save_assignments(data['assignments'])
    return jsonify({"ok": True})

# ── NFC scan endpoints ────────────────────────────────────────
@app.route('/api/nfc/scan/start', methods=['POST'])
def nfc_scan_start():
    with nfc_lock:
        if nfc_state["scanning"]:
            return jsonify({"ok": True, "msg": "Ya está escuchando"})
        nfc_state["scanning"] = True
        nfc_state["result"]   = None
        t = threading.Thread(target=nfc_scan_worker, daemon=True)
        nfc_state["thread"] = t
        t.start()
    return jsonify({"ok": True})

@app.route('/api/nfc/scan/stop', methods=['POST'])
def nfc_scan_stop():
    with nfc_lock:
        nfc_state["scanning"] = False
        nfc_state["result"]   = None
    return jsonify({"ok": True})

@app.route('/api/nfc/scan/result', methods=['GET'])
def nfc_scan_result():
    with nfc_lock:
        scanning = nfc_state["scanning"]
        result   = nfc_state["result"]
    return jsonify({"scanning": scanning, "result": result})

@app.route('/api/exit_config', methods=['POST'])
def exit_config():
    """Crea un archivo de señal para que player.py salga del modo configuración."""
    signal_file = os.path.join(BASE_DIR, "exit_config.signal")
    open(signal_file, 'w').close()
    return jsonify({"ok": True})

# ── Arranque ─────────────────────────────────────────────────
if __name__ == '__main__':
    print(f"🎵 FaPi server arrancando en http://0.0.0.0:{PORT}")
    print(f"   Audios en   : {AUDIOS_DIR}")
    print(f"   Asignaciones: {ASSIGNMENTS_FILE}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
