#!/usr/bin/env python3
"""
player.py - AleBox - Reproductor de audio con NFC

Pines:
  KY040 CLK  -> GPIO17 (Pin 11)
  KY040 DT   -> GPIO27 (Pin 13)
  KY040 SW   -> GPIO22 (Pin 15)
  MAX98357 SD -> GPIO24 (Pin 18)
  RC522 SDA  -> GPIO8  (Pin 24)
  RC522 SCK  -> GPIO11 (Pin 23)
  RC522 MOSI -> GPIO10 (Pin 19)
  RC522 MISO -> GPIO9  (Pin 21)
  RC522 RST  -> GPIO25 (Pin 22)
  BTN Config -> GPIO16 (Pin 36)
  BTN Power  -> GPIO6  (Pin 31)
  BTN Next   -> GPIO26 (Pin 37)
  BTN Prev   -> GPIO13 (Pin 33)
  BTN Aux    -> GPIO5  (Pin 29)
"""

import sys, os, time, json, random, socket, subprocess, threading

import vlc
from gpiozero import LED, Button

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'aux'))
from ky040 import KY040
from hotspot import HotspotManager

# ── Pines ────────────────────────────────────────────────────
PIN_SD         = 24
PIN_BTN_CONFIG = 16
PIN_BTN_POWER  = 6
PIN_BTN_NEXT   = 26
PIN_BTN_PREV   = 13
PIN_BTN_AUX    = 5

# ── Rutas ────────────────────────────────────────────────────
BASE_DIR           = os.path.expanduser("~/FaPi")
EXIT_CONFIG_SIGNAL = os.path.join(BASE_DIR, "exit_config.signal")
AUDIOS_DIR         = os.path.join(BASE_DIR, "audios")
ASSIGNMENTS_FILE   = os.path.join(BASE_DIR, "assignments.json")
POSITIONS_FILE     = os.path.join(BASE_DIR, "positions.json")
SOUNDS_DIR         = os.path.join(BASE_DIR, "sounds")
HELLO_DIR          = os.path.join(SOUNDS_DIR, "hello")
GOODBYE_DIR        = os.path.join(SOUNDS_DIR, "goodbye")
SND_NO_NETWORK     = os.path.join(SOUNDS_DIR, "no_network.wav")
SND_CONFIG_MODE    = os.path.join(SOUNDS_DIR, "configuration_mode.wav")
LED_PATH           = "/sys/class/leds/ACT/brightness"
LED_TRIGGER_PATH   = "/sys/class/leds/ACT/trigger"

# ── Configuración ────────────────────────────────────────────
VOLUME        = 50
VOLUME_STEP   = 5
VOLUME_MAX    = 150
SKIP_SECONDS  = 30    # segundos de avance/retroceso rápido
HOLD_TIME     = 1.0   # segundos para considerar pulsación larga
PREV_RESTART  = 10    # segundos al inicio para retroceder a pista anterior

# ── Estado de reproducción ───────────────────────────────────
# playlist: lista de rutas absolutas de la sesión actual
# playlist_idx: índice actual dentro de playlist
# playlist_shuffle: si la lista se reproduce en aleatorio
# ultimo_uid: UID del tag actualmente en el lector
# pausado_usuario: True si el usuario pausó manualmente
playlist        = []
playlist_idx    = 0
playlist_uid    = None   # UID al que pertenece la playlist actual
playlist_shuffle = False
modo_config     = False
server_proceso  = None
hotspot         = HotspotManager()
led_thread      = None
stop_led        = threading.Event()
pausado_usuario = False
ultimo_uid      = None
modo_repetir    = False  # no usado actualmente (reservado)
arranque_listo  = False  # False hasta que el audio de bienvenida termina

# ── GPIO ─────────────────────────────────────────────────────
amp_sd     = LED(PIN_SD)
btn_config = Button(PIN_BTN_CONFIG, pull_up=True, bounce_time=0.05)
btn_power  = Button(PIN_BTN_POWER,  pull_up=True, bounce_time=0.05)
btn_next   = Button(PIN_BTN_NEXT,   pull_up=True, bounce_time=0.05, hold_time=HOLD_TIME)
btn_prev   = Button(PIN_BTN_PREV,   pull_up=True, bounce_time=0.05, hold_time=HOLD_TIME)
btn_aux    = Button(PIN_BTN_AUX,    pull_up=True, bounce_time=0.05, hold_time=HOLD_TIME)

def amp_mute(mute):
    amp_sd.off() if mute else amp_sd.on()

# ── LED ACT ──────────────────────────────────────────────────
def led_write(v):
    try:
        open(LED_PATH, 'w').write(str(v))
    except Exception:
        pass

def led_fijo(on=True):
    stop_led.set()
    try:
        open(LED_TRIGGER_PATH, 'w').write('none')
    except Exception:
        pass
    time.sleep(0.05)
    led_write(1 if on else 0)

def led_parpadeo(intervalo=0.2):
    stop_led.clear()
    try:
        open(LED_TRIGGER_PATH, 'w').write('none')
    except Exception:
        pass
    def _blink():
        e = 0
        while not stop_led.is_set():
            led_write(e); e = 1 - e; time.sleep(intervalo)
        led_write(0)
    global led_thread
    led_thread = threading.Thread(target=_blink, daemon=True)
    led_thread.start()

def led_restaurar():
    stop_led.set()
    try:
        open(LED_TRIGGER_PATH, 'w').write('mmc0')
    except Exception:
        pass

# ── Persistencia de posiciones ───────────────────────────────
def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_position(uid, track_path, time_ms):
    positions = load_positions()
    positions[uid] = {"track": track_path, "time_ms": time_ms}
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(positions, f, indent=2)
    print(f"  Posición guardada: {os.path.basename(track_path)} @ {time_ms//1000}s")

def get_position(uid):
    return load_positions().get(uid)

# ── Assignments ───────────────────────────────────────────────
def load_assignments():
    if os.path.exists(ASSIGNMENTS_FILE):
        with open(ASSIGNMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def uid_to_hex(uid_int):
    h = format(uid_int, '08X')
    return ':'.join(h[i:i+2] for i in range(0, len(h), 2)).lstrip('0:').lstrip('0') or '00'

# ── Playlist helpers ─────────────────────────────────────────
AUDIO_EXTS = ('.wav', '.mp3', '.ogg', '.m4a')

def build_playlist(assignment):
    """
    Dada una asignación (nombre de archivo o carpeta), devuelve
    (lista_de_rutas_absolutas, shuffle).
    - Si es un archivo: lista de un elemento, shuffle=False
    - Si es una carpeta: archivos ordenados por nombre, shuffle según asignación
    """
    global playlist_shuffle
    # assignment puede ser "archivo.mp3" o {"folder": "nombre", "shuffle": bool}
    if isinstance(assignment, dict):
        folder  = assignment.get("folder", "")
        shuffle = assignment.get("shuffle", False)
        folder_path = os.path.join(AUDIOS_DIR, folder)
        if os.path.isdir(folder_path):
            tracks = sorted([
                os.path.join(folder_path, f)
                for f in os.listdir(folder_path)
                if f.lower().endswith(AUDIO_EXTS)
            ])
            if shuffle:
                random.shuffle(tracks)
            playlist_shuffle = shuffle
            return tracks
        return []
    else:
        # archivo individual
        playlist_shuffle = False
        path = os.path.join(AUDIOS_DIR, assignment)
        return [path] if os.path.exists(path) else []

# ── VLC ──────────────────────────────────────────────────────
vlc_instance = vlc.Instance("--aout=alsa", "--alsa-audio-device=default")
player       = vlc_instance.media_player_new()

def set_volume(vol):
    vol = max(0, min(VOLUME_MAX, vol))
    player.audio_set_volume(vol)
    if vol > 0 and player.get_state() == vlc.State.Playing:
        amp_mute(False)
    elif vol == 0:
        amp_mute(True)
    return vol

def _esperar_playing(timeout=3.0):
    for _ in range(int(timeout / 0.1)):
        time.sleep(0.1)
        if player.get_state() == vlc.State.Playing:
            return True
    return False

def reproducir_pista(path, start_ms=0):
    """Carga y reproduce una pista, opcionalmente desde start_ms."""
    if not path or not os.path.exists(path):
        print(f"  Audio no encontrado: {path}")
        return
    amp_mute(True)
    media = vlc_instance.media_new(path)
    player.set_media(media)
    player.play()
    _esperar_playing()
    if start_ms > 0:
        player.set_time(start_ms)
    time.sleep(0.1)
    amp_mute(False)
    print(f"  ▶ {os.path.basename(path)}" + (f" desde {start_ms//1000}s" if start_ms else ""))

def reproducir_y_esperar(path):
    """Reproduce y bloquea hasta que termina. Para hello/goodbye/notificaciones."""
    if not path or not os.path.exists(path):
        return
    amp_mute(True)
    media = vlc_instance.media_new(path)
    player.set_media(media)
    player.play()
    _esperar_playing()
    time.sleep(0.1)
    amp_mute(False)
    print(f"  ♪ {os.path.basename(path)}")
    while True:
        state = player.get_state()
        if state not in (vlc.State.Playing, vlc.State.Opening, vlc.State.Buffering):
            break
        remaining = player.get_length() - player.get_time()
        if 0 < remaining < 300:
            amp_mute(True)
        time.sleep(0.05)
    amp_mute(True)

def iniciar_playlist(uid, assignment):
    """Construye y arranca la playlist para un uid, respetando posición guardada."""
    global playlist, playlist_idx, playlist_uid, pausado_usuario
    tracks = build_playlist(assignment)
    if not tracks:
        print(f"  Sin pistas para reproducir")
        return
    playlist     = tracks
    playlist_uid = uid
    pausado_usuario = False

    # ¿Hay posición guardada?
    pos = get_position(uid)
    start_ms  = 0
    start_idx = 0
    if pos:
        saved_track = pos.get("track")
        saved_ms    = pos.get("time_ms", 0)
        if saved_track in tracks:
            start_idx = tracks.index(saved_track)
            start_ms  = saved_ms
            print(f"  Reanudando desde posición guardada")

    playlist_idx = start_idx
    reproducir_pista(playlist[playlist_idx], start_ms)

def pista_siguiente(forzar=False):
    """Avanza a la siguiente pista. Si forzar=False solo avanza si hay playlist."""
    global playlist_idx, pausado_usuario
    if not playlist:
        return
    if playlist_idx >= len(playlist) - 1:
        print("  Ya es la última pista")
        return
    playlist_idx   += 1
    pausado_usuario = False
    reproducir_pista(playlist[playlist_idx])

def pista_anterior():
    """Retrocede a la pista anterior de la playlist."""
    global playlist_idx, pausado_usuario
    if not playlist or playlist_idx <= 0:
        print("  Ya es la primera pista")
        return
    playlist_idx   -= 1
    pausado_usuario = False
    reproducir_pista(playlist[playlist_idx])

# ── Controles de reproducción ─────────────────────────────────
def audio_aleatorio(carpeta):
    if not os.path.isdir(carpeta):
        return None
    archivos = [f for f in os.listdir(carpeta) if f.lower().endswith(AUDIO_EXTS)]
    return os.path.join(carpeta, random.choice(archivos)) if archivos else None

def hay_red():
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False

def toggle_play_pause():
    global pausado_usuario
    state = player.get_state()
    if state == vlc.State.Playing:
        amp_mute(True)
        time.sleep(0.05)
        player.pause()
        pausado_usuario = True
        print("  ⏸ Pausado")
    elif state in (vlc.State.Paused, vlc.State.Stopped,
                   vlc.State.NothingSpecial, vlc.State.Ended):
        pausado_usuario = False
        player.play()
        _esperar_playing()
        time.sleep(0.1)
        amp_mute(False)
        print("  ▶ Reproduciendo")

def _seek(nuevo_ms, etiqueta):
    """Salta a nuevo_ms de forma limpia: mutea, salta y desmutea en hilo separado.
    El lock evita que dos seeks se solapen."""
    if not seek_lock.acquire(blocking=False):
        return
    estaba_playing = player.get_state() == vlc.State.Playing
    amp_mute(True)
    player.set_time(nuevo_ms)

    def _desmutear():
        time.sleep(0.7)
        if estaba_playing:
            amp_mute(False)
        seek_lock.release()

    threading.Thread(target=_desmutear, daemon=True).start()
    print(f"  {etiqueta} → {nuevo_ms//1000}s")

def avanzar_30s():
    if player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
        return
    length  = player.get_length()
    current = player.get_time()
    nuevo   = min(current + SKIP_SECONDS * 1000, length - 1000)
    _seek(nuevo, f"⏩ +{SKIP_SECONDS}s")

def retroceder_30s():
    if player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
        return
    current = player.get_time()
    nuevo   = max(current - SKIP_SECONDS * 1000, 0)
    _seek(nuevo, f"⏪ -{SKIP_SECONDS}s")

def ir_al_inicio():
    global pausado_usuario
    pausado_usuario = False
    if player.get_state() in (vlc.State.Playing, vlc.State.Paused):
        _seek(0, "⏮ Inicio de pista")

# ── Callbacks botones ─────────────────────────────────────────

# -- KY040 --
def on_subir(valor):
    global VOLUME
    if modo_config: return
    VOLUME = set_volume(min(VOLUME + VOLUME_STEP, VOLUME_MAX))
    print(f"  🔊 {VOLUME}%")

def on_bajar(valor):
    global VOLUME
    if modo_config: return
    VOLUME = set_volume(max(VOLUME - VOLUME_STEP, 0))
    print(f"  🔉 {VOLUME}%")

def on_press():
    if modo_config: return
    toggle_play_pause()

def on_hold():
    if modo_config: return
    ir_al_inicio()

# -- Siguiente (GPIO26) --
def on_next_press():
    """Pulsación corta: avanzar 30s."""
    if modo_config: return
    avanzar_30s()

def on_next_hold():
    """Pulsación larga: siguiente pista."""
    if modo_config: return
    pista_siguiente()

# -- Anterior (GPIO13) --
def on_prev_press():
    """Pulsación corta: retroceder 30s."""
    if modo_config: return
    retroceder_30s()

def on_prev_hold():
    """
    Pulsación larga:
      - Si llevamos más de PREV_RESTART segundos → ir al inicio de la pista
      - Si llevamos menos → ir a la pista anterior
    """
    if modo_config: return
    current_s = player.get_time() / 1000
    if current_s <= PREV_RESTART and len(playlist) > 1:
        pista_anterior()
    else:
        ir_al_inicio()

# -- Auxiliar (GPIO5): guardar posición (corto) / borrar posición (largo) --
def on_aux_press():
    if modo_config: return
    state = player.get_state()
    if state not in (vlc.State.Playing, vlc.State.Paused):
        print("  Sin reproducción activa para guardar")
        return
    if not playlist_uid:
        print("  Sin tag activo")
        return
    track   = playlist[playlist_idx] if playlist else None
    time_ms = max(player.get_time() - 20000, 0)  # restar 20s para recordar contexto
    if track:
        save_position(playlist_uid, track, time_ms)

def on_aux_hold():
    if modo_config: return
    if not playlist_uid:
        print("  Sin tag activo")
        return
    positions = load_positions()
    if playlist_uid in positions:
        del positions[playlist_uid]
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
        print(f"  Posición eliminada para {playlist_uid}")
    else:
        print("  No había posición guardada para este tag")

# ── Modo configuración ────────────────────────────────────────
def entrar_modo_config():
    global modo_config, server_proceso
    if modo_config: return

    print("\n  Comprobando red...")
    if not hay_red():
        print("  Sin red. Iniciando hotspot temporal...")
        hotspot.start()
	
    
    modo_config = True
    print("\n── Modo configuración ──────────────────")
    if player.get_state() == vlc.State.Playing:
        player.pause()
    amp_mute(True)
    reproducir_y_esperar(SND_CONFIG_MODE)
    time.sleep(0.5)
    if nfc_reader is not None:
        try:
            nfc_reader.READER.Close_MFRC522()
        except Exception:
            pass
    time.sleep(0.2)

    led_parpadeo(intervalo=0.2)

    venv_python   = os.path.join(BASE_DIR, "venv/bin/python3")
    server_script = os.path.join(BASE_DIR, "server.py")
    server_proceso = subprocess.Popen([venv_python, server_script], cwd=BASE_DIR)
    print("  Servidor web iniciado")

def salir_modo_config():
    global modo_config, server_proceso, nfc_reader, nfc_rdr
    if not modo_config: return
    modo_config = False
    print("\n── Modo reproductor ────────────────────")
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
        server_proceso.wait()
        print("  Servidor detenido")
    if hotspot.active:
        hotspot.stop()
    led_fijo(True)
    nfc_reader = None
    nfc_rdr    = None
    threading.Thread(target=nfc_loop, daemon=True).start()
    print("  Listo")

def on_btn_config():
    if not modo_config:
        entrar_modo_config()
    else:
        salir_modo_config()

# ── Apagado ───────────────────────────────────────────────────
def on_btn_power():
    print("\n── Apagando ────────────────────────────")
    amp_mute(True)
    player.stop()
    audio = audio_aleatorio(GOODBYE_DIR)
    if audio:
        reproducir_y_esperar(audio)
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
    if hotspot.active:
        hotspot.stop()
    encoder.close()
    led_restaurar()
    print("  Apagando el sistema...")
    subprocess.run(["sudo", "poweroff"])

# ── NFC ──────────────────────────────────────────────────────
nfc_reader = None
nfc_rdr    = None

def suprimir_salida():
    devnull = os.open(os.devnull, os.O_WRONLY)
    o, e = os.dup(1), os.dup(2)
    os.dup2(devnull, 1); os.dup2(devnull, 2); os.close(devnull)
    return o, e

def restaurar_salida(o, e):
    os.dup2(o, 1); os.dup2(e, 2); os.close(o); os.close(e)

def nfc_loop():
    global ultimo_uid, pausado_usuario, nfc_reader, nfc_rdr
    try:
        from mfrc522 import SimpleMFRC522
        nfc_reader = SimpleMFRC522()
        nfc_rdr    = nfc_reader.READER
        reader, rdr = nfc_reader, nfc_rdr
        print("  Lector NFC listo")
        while True:
            if not arranque_listo or modo_config:
                time.sleep(0.2)
                continue
            old = suprimir_salida()
            uid, _ = reader.read_no_block()
            try: rdr.MFRC522_StopCrypto1()
            except Exception: pass
            restaurar_salida(*old)

            if uid:
                uid_hex    = uid_to_hex(uid)
                assignment = load_assignments().get(uid_hex)
                if uid_hex != ultimo_uid:
                    ultimo_uid      = uid_hex
                    pausado_usuario = False
                    if assignment:
                        print(f"\n  Tag: {uid_hex}")
                        iniciar_playlist(uid_hex, assignment)
                    else:
                        print(f"\n  Tag {uid_hex} sin asignar")

            # Avance automático al final de pista en playlist
            state = player.get_state()
            if state == vlc.State.Ended and playlist:
                if playlist_idx < len(playlist) - 1:
                    time.sleep(0.3)
                    pista_siguiente()
                # si es la última, se queda parado

            time.sleep(0.2)
    except Exception as e:
        import traceback
        print(f"  Error NFC: {e}"); traceback.print_exc()

# ── Arranque ──────────────────────────────────────────────────
print("════════════════════════════════════════")
print("  AleBox - Reproductor")
print("════════════════════════════════════════")
print("  KY040  : volumen / pausa / hold=inicio pista")
print("  GPIO26 : ⏩ +30s / hold=siguiente pista")
print("  GPIO13 : ⏪ -30s / hold=inicio o anterior")
print("  GPIO5  : guardar posición")
print("  GPIO16 : modo configuración")
print("  GPIO6  : apagado")
print("════════════════════════════════════════\n")

amp_mute(True)
set_volume(VOLUME)
led_fijo(True)

encoder = KY040(
    clk=17, dt=27, sw=22,
    on_clockwise=on_subir,
    on_counter_clockwise=on_bajar,
    on_press=on_press,
    on_hold=on_hold,
    max_steps=VOLUME_MAX, min_steps=0,
    hold_time=HOLD_TIME, bounce_time=0.05,
)
encoder.value = VOLUME

btn_config.when_pressed = on_btn_config
btn_power.when_pressed  = on_btn_power
btn_next.when_pressed   = on_next_press
btn_next.when_held      = on_next_hold
btn_prev.when_pressed   = on_prev_press
btn_prev.when_held      = on_prev_hold
btn_aux.when_pressed    = on_aux_press
btn_aux.when_held       = on_aux_hold

threading.Thread(target=nfc_loop, daemon=True).start()

audio_hello = audio_aleatorio(HELLO_DIR)
if audio_hello:
    print(f"  Bienvenida: {os.path.basename(audio_hello)}")
    reproducir_y_esperar(audio_hello)

arranque_listo = True

# ── Bucle principal ───────────────────────────────────────────
try:
    while True:
        if modo_config and os.path.exists(EXIT_CONFIG_SIGNAL):
            os.remove(EXIT_CONFIG_SIGNAL)
            salir_modo_config()
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nSaliendo...")
finally:
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
    amp_mute(True)
    player.stop()
    encoder.close()
    led_restaurar()
