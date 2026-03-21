#!/usr/bin/env python3
"""
player.py - Reproductor de audio con NFC, KY040 y modo configuración

Flujo:
  - Al arrancar reproduce un audio aleatorio de sounds/hello/
  - Lee assignments.json y espera tags NFC para reproducir el audio asignado
  - La clase KY040 (gpiozero) gestiona volumen, play/pause y reinicio
  - El botón de configuración comprueba red, reproduce sounds/no_network.wav
    o sounds/configuration_mode.wav y lanza el servidor web
  - El botón de apagado reproduce un audio aleatorio de sounds/goodbye/
    y apaga el sistema de forma segura
  - El LED ACT indica el modo: fijo=reproducción, parpadeo=config

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

Botón apagado:
  Pin 1 -> GPIO16 (Pin 36)
  Pin 2 -> GND    (Pin 34)
"""

import sys
import os
import time
import json
import random
import socket
import subprocess
import threading

import vlc
from gpiozero import LED, Button

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'aux'))
from ky040 import KY040

# ── Pines ────────────────────────────────────────────────────
PIN_SD          = 24   # Mute amplificador MAX98357A
PIN_BTN_CONFIG  = 23   # Botón modo configuración
PIN_BTN_POWER   = 16   # Botón apagado

# ── Rutas ────────────────────────────────────────────────────
BASE_DIR         = os.path.expanduser("~/FaPi")
EXIT_CONFIG_SIGNAL = os.path.join(BASE_DIR, "exit_config.signal")
AUDIOS_DIR       = os.path.join(BASE_DIR, "audios")
ASSIGNMENTS_FILE = os.path.join(BASE_DIR, "assignments.json")
SOUNDS_DIR       = os.path.join(BASE_DIR, "sounds")
HELLO_DIR        = os.path.join(SOUNDS_DIR, "hello")
GOODBYE_DIR      = os.path.join(SOUNDS_DIR, "goodbye")
SND_NO_NETWORK   = os.path.join(SOUNDS_DIR, "no_network.wav")
SND_CONFIG_MODE  = os.path.join(SOUNDS_DIR, "configuration_mode.wav")
LED_PATH         = "/sys/class/leds/ACT/brightness"
LED_TRIGGER_PATH = "/sys/class/leds/ACT/trigger"

# ── Configuración ────────────────────────────────────────────
VOLUME      = 30   # Volumen inicial (0-100)
VOLUME_STEP = 2    # Cambio por tick del encoder
VOLUME_MAX  = 80   # Volumen máximo (ajustar para evitar distorsión)

# ── Estado global ────────────────────────────────────────────
modo_config     = False
server_proceso  = None
led_thread      = None
stop_led        = threading.Event()
pausado_usuario = False
ultimo_uid      = None

# ── GPIO (gpiozero) ──────────────────────────────────────────
amp_sd     = LED(PIN_SD)
btn_config = Button(PIN_BTN_CONFIG, pull_up=True, bounce_time=0.05)
btn_power  = Button(PIN_BTN_POWER,  pull_up=True, bounce_time=0.05)

def amp_mute(mute):
    if mute:
        amp_sd.off()
    else:
        amp_sd.on()

# ── LED ACT ──────────────────────────────────────────────────
def led_write(valor):
    try:
        with open(LED_PATH, 'w') as f:
            f.write(str(valor))
    except Exception:
        pass

def led_fijo(encendido=True):
    stop_led.set()
    try:
        with open(LED_TRIGGER_PATH, 'w') as f:
            f.write('none')
    except Exception:
        pass
    time.sleep(0.05)
    led_write(1 if encendido else 0)

def led_parpadeo(intervalo=0.2):
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
    stop_led.set()
    try:
        with open(LED_TRIGGER_PATH, 'w') as f:
            f.write('mmc0')
    except Exception:
        pass

# ── Utilidades de audio ───────────────────────────────────────
def audio_aleatorio(carpeta):
    """Devuelve un archivo de audio aleatorio de la carpeta dada, o None."""
    if not os.path.isdir(carpeta):
        return None
    archivos = [
        f for f in os.listdir(carpeta)
        if f.lower().endswith(('.wav', '.mp3', '.ogg', '.m4a'))
    ]
    return os.path.join(carpeta, random.choice(archivos)) if archivos else None

def hay_red():
    """Comprueba si hay conexión a internet intentando conectar a DNS de Google."""
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False

# ── Assignments ───────────────────────────────────────────────
def load_assignments():
    if os.path.exists(ASSIGNMENTS_FILE):
        with open(ASSIGNMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def uid_to_hex(uid_int):
    h = format(uid_int, '08X')
    return ':'.join(h[i:i+2] for i in range(0, len(h), 2)).lstrip('0:').lstrip('0') or '00'

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

def reproducir(audio_path):
    """Reproduce un audio y espera a que VLC esté realmente en Playing."""
    if not audio_path or not os.path.exists(audio_path):
        print(f"  Audio no encontrado: {audio_path}")
        return
    amp_mute(True)
    media = vlc_instance.media_new(audio_path)
    player.set_media(media)
    player.play()
    for _ in range(30):
        time.sleep(0.1)
        if player.get_state() == vlc.State.Playing:
            break
    time.sleep(0.1)
    amp_mute(False)
    print(f"  Reproduciendo: {os.path.basename(audio_path)}")

def reproducir_y_esperar(audio_path):
    """Reproduce un audio y bloquea hasta que termina (para hello/goodbye)."""
    if not audio_path or not os.path.exists(audio_path):
        print(f"  Audio no encontrado: {audio_path}")
        return
    amp_mute(True)
    media = vlc_instance.media_new(audio_path)
    player.set_media(media)
    player.play()
    for _ in range(30):
        time.sleep(0.1)
        if player.get_state() == vlc.State.Playing:
            break
    time.sleep(0.1)
    amp_mute(False)
    print(f"  Reproduciendo: {os.path.basename(audio_path)}")
    # Esperar a que termine, muteando antes del final para evitar el pop
    while True:
        state = player.get_state()
        if state not in (vlc.State.Playing, vlc.State.Opening, vlc.State.Buffering):
            break
        # Mutear 300ms antes del final para evitar el pop de cierre del stream
        remaining = player.get_length() - player.get_time()
        if 0 < remaining < 300:
            amp_mute(True)
        time.sleep(0.05)
    amp_mute(True)

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

def reiniciar_pista():
    global pausado_usuario, ultimo_uid
    pausado_usuario = False
    ultimo_uid      = None
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
        print("  Pista reiniciada")

# ── Callbacks KY040 ──────────────────────────────────────────
def on_subir(valor):
    global VOLUME
    if modo_config:
        return
    VOLUME = set_volume(min(VOLUME + VOLUME_STEP, VOLUME_MAX))
    print(f"  ↑ Volumen: {VOLUME}%")

def on_bajar(valor):
    global VOLUME
    if modo_config:
        return
    VOLUME = set_volume(max(VOLUME - VOLUME_STEP, 0))
    print(f"  ↓ Volumen: {VOLUME}%")

def on_press():
    if modo_config:
        return
    toggle_play_pause()

def on_hold():
    if modo_config:
        return
    reiniciar_pista()

# ── Modo configuración ────────────────────────────────────────
def entrar_modo_config():
    global modo_config, server_proceso
    if modo_config:
        return

    # Comprobar red antes de entrar
    print("\n  Comprobando red...")
    if not hay_red():
        print("  Sin red — no se puede entrar en modo configuración")
        reproducir_y_esperar(SND_NO_NETWORK)
        return

    modo_config = True
    print("\n── Modo configuración ──────────────────")

    if player.get_state() == vlc.State.Playing:
        player.pause()
    amp_mute(True)

    reproducir_y_esperar(SND_CONFIG_MODE)

    # Esperar a que el hilo NFC entre en pausa antes de liberar el lector
    time.sleep(0.5)
    # Liberar el lector NFC para que server.py pueda usarlo
    if nfc_reader is not None:
        try:
            nfc_reader.READER.Close_MFRC522()
        except Exception:
            pass
    time.sleep(0.2)

    led_parpadeo(intervalo=0.2)

    venv_python   = os.path.join(BASE_DIR, "venv/bin/python3")
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

    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
        server_proceso.wait()
        print("  Servidor web detenido")

    led_fijo(True)

    # Reiniciar el hilo NFC para que reabra el lector SPI
    global nfc_reader, nfc_rdr
    nfc_reader = None
    nfc_rdr    = None
    t = threading.Thread(target=nfc_loop, daemon=True)
    t.start()
    print("  Listo para leer tags NFC")

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

    # Reproducir goodbye aleatorio y esperar a que termine
    audio = audio_aleatorio(GOODBYE_DIR)
    if audio:
        reproducir_y_esperar(audio)

    # Limpiar
    if server_proceso and server_proceso.poll() is None:
        server_proceso.terminate()
    encoder.close()
    led_restaurar()

    print("  Apagando el sistema...")
    subprocess.run(["sudo", "poweroff"])

# ── NFC en hilo separado ──────────────────────────────────────
nfc_reader = None
nfc_rdr    = None
def suprimir_salida():
    devnull    = os.open(os.devnull, os.O_WRONLY)
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    return old_stdout, old_stderr

def restaurar_salida(old_stdout, old_stderr):
    os.dup2(old_stdout, 1)
    os.dup2(old_stderr, 2)
    os.close(old_stdout)
    os.close(old_stderr)

def nfc_loop():
    global ultimo_uid, pausado_usuario, nfc_reader, nfc_rdr
    try:
        from mfrc522 import SimpleMFRC522
        nfc_reader = SimpleMFRC522()
        nfc_rdr    = nfc_reader.READER
        reader     = nfc_reader
        rdr        = nfc_rdr
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
                uid_hex    = uid_to_hex(uid)
                audio_name = load_assignments().get(uid_hex)

                if uid_hex != ultimo_uid:
                    ultimo_uid      = uid_hex
                    pausado_usuario = False
                    if audio_name:
                        print(f"\n  Tag: {uid_hex} → {audio_name}")
                        reproducir(os.path.join(AUDIOS_DIR, audio_name))
                    else:
                        print(f"\n  Tag {uid_hex} sin asignar")

            time.sleep(0.2)
    except Exception as e:
        import traceback
        print(f"  Error NFC: {e}")
        traceback.print_exc()

# ── Arranque ──────────────────────────────────────────────────
print("════════════════════════════════════════")
print("  FaPi - Reproductor")
print("════════════════════════════════════════")
print("  Encoder : volumen / play-pause / hold=reiniciar")
print("  BTN CFG : modo configuración (GPIO23)")
print("  BTN PWR : apagado seguro    (GPIO16)")
print("  Ctrl+C  : salir")
print("════════════════════════════════════════\n")

amp_mute(True)
set_volume(VOLUME)
led_fijo(True)

# Inicializar KY040
encoder = KY040(
    clk=17, dt=27, sw=22,
    on_clockwise=on_subir,
    on_counter_clockwise=on_bajar,
    on_press=on_press,
    on_hold=on_hold,
    max_steps=VOLUME_MAX,
    min_steps=0,
    hold_time=1.0,
    bounce_time=0.05,
)
encoder.value = VOLUME

# Botones
btn_config.when_pressed = on_btn_config
btn_power.when_pressed  = on_btn_power

# Hilo NFC
nfc_thread = threading.Thread(target=nfc_loop, daemon=True)
nfc_thread.start()

# Audio de bienvenida
audio_hello = audio_aleatorio(HELLO_DIR)
if audio_hello:
    print(f"  Bienvenida: {os.path.basename(audio_hello)}")
    reproducir_y_esperar(audio_hello)

# ── Bucle principal ───────────────────────────────────────────
try:
    while True:
        # Comprobar señal de salida del modo configuración
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
