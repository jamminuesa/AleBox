#!/usr/bin/env python3
"""
player.py - Reproductor de audio con NFC, KY040 y modo configuración

Flujo:
  - Lee assignments.json y espera tags NFC para reproducir el audio asignado
  - El encoder KY040 controla el volumen; su botón hace play/pause
  - El botón de configuración lanza el servidor web y pausa el reproductor
  - El LED ACT de la RPi indica el modo: fijo=reproducción, parpadeo=config

Conexiones KY040:
  CLK -> GPIO17 (Pin 11)
  DT  -> GPIO27 (Pin 13)
  SW  -> GPIO22 (Pin 15)
  VCC -> 3.3V   (Pin 17)
  GND -> GND    (Pin 9)

Conexiones MAX98357A:
  VIN  -> 5V     (Pin 2)
  GND  -> GND    (Pin 6)
  BCLK -> GPIO18 (Pin 12)
  LRC  -> GPIO19 (Pin 35)
  DIN  -> GPIO21 (Pin 40)
  SD   -> GPIO24 (Pin 18)
  GAIN -> 3.3V   (Pin 1)

Conexiones RC522:
  SDA  -> GPIO8  (Pin 24)
  SCK  -> GPIO11 (Pin 23)
  MOSI -> GPIO10 (Pin 19)
  MISO -> GPIO9  (Pin 21)
  RST  -> GPIO25 (Pin 22)
  3.3V -> Pin 17
  GND  -> Pin 25

Botón configuración:
  Pin 1 -> GPIO23 (Pin 16)
  Pin 2 -> GND    (Pin 14)
"""

import RPi.GPIO as GPIO
import vlc
import json
import os
import time
import subprocess
import threading

# ── Pines ────────────────────────────────────────────────────
CLK        = 17
DT         = 27
SW         = 22   # Botón encoder: play/pause
SD         = 24   # Mute amplificador
BTN_CONFIG = 23   # Botón modo configuración

# ── Rutas ────────────────────────────────────────────────────
BASE_DIR         = os.path.expanduser("~/FaPi")
AUDIOS_DIR       = os.path.join(BASE_DIR, "audios")
ASSIGNMENTS_FILE = os.path.join(BASE_DIR, "assignments.json")
LED_PATH         = "/sys/class/leds/ACT/brightness"
LED_TRIGGER_PATH = "/sys/class/leds/ACT/trigger"

# ── Configuración ────────────────────────────────────────────
VOLUME      = 30   # Volumen inicial (0-100)
VOLUME_STEP = 2    # Cambio por tick del encoder
VOLUME_MAX  = 65   # Volumen máximo (ajustar para evitar distorsión)

# ── Estado global ────────────────────────────────────────────
modo_config     = False
server_proceso  = None
led_thread      = None
stop_led        = threading.Event()
pausado_usuario = False  # True cuando el usuario pausa manualmente

# ── LED ACT ──────────────────────────────────────────────────
def led_write(valor):
    """Escribe en el LED ACT (requiere que trigger sea 'none')."""
    try:
        with open(LED_PATH, 'w') as f:
            f.write(str(valor))
    except Exception:
        pass

def led_fijo(encendido=True):
    """LED fijo encendido o apagado."""
    stop_led.set()
    try:
        with open(LED_TRIGGER_PATH, 'w') as f:
            f.write('none')
    except Exception:
        pass
    time.sleep(0.05)
    led_write(1 if encendido else 0)

def led_parpadeo(intervalo=0.2):
    """LED parpadeando en hilo separado."""
    stop_led.clear()
    try:
        with open(LED_TRIGGER_PATH, 'w') as f:
            f.write('none')
    except Exception:
        pass
    def _blink():
        estado = 0
        while not stop_led.is_set():
            led_write(estado)
            estado = 1 - estado
            time.sleep(intervalo)
        led_write(0)
    global led_thread
    led_thread = threading.Thread(target=_blink, daemon=True)
    led_thread.start()

def led_restaurar():
    """Devuelve el LED al comportamiento normal del sistema (actividad SD)."""
    stop_led.set()
    try:
        with open(LED_TRIGGER_PATH, 'w') as f:
            f.write('mmc0')
    except Exception:
        pass

# ── Assignments ───────────────────────────────────────────────
def load_assignments():
    if os.path.exists(ASSIGNMENTS_FILE):
        with open(ASSIGNMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def uid_to_hex(uid_int):
    h = format(uid_int, '08X')
    return ':'.join(h[i:i+2] for i in range(0, len(h), 2)).lstrip('0:').lstrip('0') or '00'

# ── GPIO setup ───────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(CLK,        GPIO.IN,  pull_up_down=GPIO.PUD_UP)
GPIO.setup(DT,         GPIO.IN,  pull_up_down=GPIO.PUD_UP)
GPIO.setup(SW,         GPIO.IN,  pull_up_down=GPIO.PUD_UP)
GPIO.setup(SD,         GPIO.OUT)
GPIO.setup(BTN_CONFIG, GPIO.IN,  pull_up_down=GPIO.PUD_UP)
GPIO.output(SD, GPIO.LOW)

# ── VLC ──────────────────────────────────────────────────────
vlc_instance = vlc.Instance("--aout=alsa", "--alsa-audio-device=default")
player       = vlc_instance.media_player_new()

def amp_mute(mute):
    GPIO.output(SD, GPIO.LOW if mute else GPIO.HIGH)

def set_volume(vol):
    vol = max(0, min(VOLUME_MAX, vol))
    player.audio_set_volume(vol)
    if vol > 0 and player.get_state() == vlc.State.Playing:
        amp_mute(False)
    elif vol == 0:
        amp_mute(True)
    return vol

def reproducir(audio_path):
    if not os.path.exists(audio_path):
        print(f"  Audio no encontrado: {audio_path}")
        return
    amp_mute(True)
    media = vlc_instance.media_new(audio_path)
    player.set_media(media)
    player.play()
    # Esperar a que VLC esté realmente enviando audio antes de desmutear
    for _ in range(30):  # máximo 3 segundos
        time.sleep(0.1)
        if player.get_state() == vlc.State.Playing:
            break
    time.sleep(0.1)  # pequeño margen extra para que el stream I2S se estabilice
    amp_mute(False)
    print(f"  Reproduciendo: {os.path.basename(audio_path)}")

def toggle_play_pause():
    global pausado_usuario
    state = player.get_state()
    if state == vlc.State.Playing:
        amp_mute(True)
        time.sleep(0.05)
        player.pause()
        pausado_usuario = True
        print("  Pausado")
    elif state in (vlc.State.Paused, vlc.State.Stopped,
                   vlc.State.NothingSpecial, vlc.State.Ended):
        pausado_usuario = False
        player.play()
        for _ in range(30):
            time.sleep(0.1)
            if player.get_state() == vlc.State.Playing:
                break
        time.sleep(0.1)
        amp_mute(False)
        print("  Reproduciendo...")

# ── Modo configuración ────────────────────────────────────────
def entrar_modo_config():
    global modo_config, server_proceso
    if modo_config:
        return
    modo_config = True
    print("\n── Modo configuración ──────────────────")

    # Pausar audio y mutear
    if player.get_state() == vlc.State.Playing:
        player.pause()
    amp_mute(True)

    # LED parpadeo rápido
    led_parpadeo(intervalo=0.2)

    # Lanzar servidor web
    venv_python  = os.path.join(BASE_DIR, "venv/bin/python3")
    server_script = os.path.join(BASE_DIR, "server.py")
    server_proceso = subprocess.Popen(
        [venv_python, server_script],
        cwd=BASE_DIR
    )
    print("  Servidor web iniciado en http://<ip>:8000")
    print("  Pulsa el botón de nuevo para volver al reproductor")

def salir_modo_config():
    global modo_config, server_proceso
    if not modo_config:
        return
    modo_config = False
    print("\n── Modo reproductor ────────────────────")

    # Detener servidor web
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
        server_proceso.wait()
        print("  Servidor web detenido")

    # LED fijo encendido
    led_fijo(True)
    # Mantener amp muteado - se desmuteará cuando se reproduzca audio
    print("  Listo para leer tags NFC")

# ── NFC en hilo separado ──────────────────────────────────────
ultimo_uid = None

def suprimir_salida():
    """Redirige stdout y stderr a /dev/null a nivel de OS."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    return old_stdout, old_stderr

def restaurar_salida(old_stdout, old_stderr):
    """Restaura stdout y stderr."""
    os.dup2(old_stdout, 1)
    os.dup2(old_stderr, 2)
    os.close(old_stdout)
    os.close(old_stderr)

def nfc_loop():
    global ultimo_uid
    try:
        from mfrc522 import SimpleMFRC522
        reader  = SimpleMFRC522()
        rdr     = reader.READER
        print("  Lector NFC listo")
        while True:
            if modo_config:
                time.sleep(0.5)
                continue

            old = suprimir_salida()
            uid, _ = reader.read_no_block()
            try:
                rdr.MFRC522_StopCrypto1()
            except Exception:
                pass
            restaurar_salida(*old)

            if uid:
                uid_hex     = uid_to_hex(uid)
                assignments = load_assignments()
                audio_name  = assignments.get(uid_hex)

                if uid_hex != ultimo_uid:
                    # Tag distinto: reproducir siempre
                    ultimo_uid      = uid_hex
                    pausado_usuario = False
                    if audio_name:
                        audio_path = os.path.join(AUDIOS_DIR, audio_name)
                        print(f"\n  Tag: {uid_hex} → {audio_name}")
                        reproducir(audio_path)
                    else:
                        print(f"\n  Tag {uid_hex} sin asignar")
                # Mismo tag: no hacer nada (respeta pausa manual)

            time.sleep(0.2)
    except Exception as e:
        import traceback
        print(f"  Error NFC: {e}")
        traceback.print_exc()

# ── Arranque ──────────────────────────────────────────────────
print("════════════════════════════════════════")
print("  FaPi - Reproductor")
print("════════════════════════════════════════")
print("  Encoder : volumen / play-pause")
print("  BTN CFG : modo configuración (GPIO23)")
print("  Ctrl+C  : salir")
print("════════════════════════════════════════\n")

set_volume(VOLUME)
led_fijo(True)

# Arrancar hilo NFC
nfc_thread = threading.Thread(target=nfc_loop, daemon=True)
nfc_thread.start()

ultimo_clk     = GPIO.input(CLK)
ultimo_btn_cfg = GPIO.HIGH
ultimo_tick    = 0  # timestamp del último tick válido del encoder

# ── Bucle principal ───────────────────────────────────────────
try:
    while True:
        # ── Botón configuración ──────────────────────────────
        btn_cfg = GPIO.input(BTN_CONFIG)
        if btn_cfg == GPIO.LOW and ultimo_btn_cfg == GPIO.HIGH:
            time.sleep(0.05)  # debounce
            if GPIO.input(BTN_CONFIG) == GPIO.LOW:
                if not modo_config:
                    entrar_modo_config()
                else:
                    salir_modo_config()
        ultimo_btn_cfg = btn_cfg

        # ── Encoder y botón play/pause (solo en modo reproductor) ──
        if not modo_config:
            clk = GPIO.input(CLK)
            if clk != ultimo_clk:
                dt = GPIO.input(DT)
                if clk == GPIO.LOW:  # solo en flanco de bajada
                    ahora = time.monotonic()
                    if ahora - ultimo_tick > 0.05:  # ignorar eventos < 50ms
                        ultimo_tick = ahora
                        if dt == GPIO.HIGH:
                            VOLUME = min(VOLUME + VOLUME_STEP, VOLUME_MAX)
                            direccion = "↑ Sube"
                        else:
                            VOLUME = max(VOLUME - VOLUME_STEP, 0)
                            direccion = "↓ Baja"
                        VOLUME = set_volume(VOLUME)
                        estado_amp = "ON" if GPIO.input(SD) == GPIO.HIGH else "MUTE"
                        print(f"  {direccion} | Volumen: {VOLUME}% | Amp: {estado_amp}")
            ultimo_clk = clk

            if GPIO.input(SW) == GPIO.LOW:
                press_start = time.monotonic()
                # Esperar a que se suelte para medir duración
                while GPIO.input(SW) == GPIO.LOW:
                    time.sleep(0.01)
                duracion = time.monotonic() - press_start

                if duracion >= 1.0:
                    # Pulsación larga: reiniciar pista desde el inicio
                    pausado_usuario = False
                    ultimo_uid      = None  # forzar re-detección del tag
                    state = player.get_state()
                    if state in (vlc.State.Playing, vlc.State.Paused):
                        amp_mute(True)
                        player.stop()
                        time.sleep(0.1)
                        player.play()
                        for _ in range(30):
                            time.sleep(0.1)
                            if player.get_state() == vlc.State.Playing:
                                break
                        time.sleep(0.1)
                        amp_mute(False)
                        print("  Reiniciando pista desde el inicio")
                else:
                    # Pulsación corta: play/pause
                    toggle_play_pause()
                time.sleep(0.05)

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nSaliendo...")
finally:
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
    amp_mute(True)
    player.stop()
    led_restaurar()
    GPIO.cleanup()
