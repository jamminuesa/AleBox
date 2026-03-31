#!/usr/bin/env python3
"""
hotspot.py - Gestión del hotspot temporal AleBox-Setup
Usado por player.py cuando no hay red disponible al entrar en modo config.

Uso interno:
  from hotspot import HotspotManager
  hs = HotspotManager()
  hs.start()   → activa el hotspot
  hs.stop()    → desactiva el hotspot
  hs.active    → True si el hotspot está activo
"""

import subprocess
import time

HOTSPOT_SSID     = "AleBox-Setup"
HOTSPOT_PASSWORD = "alebox123"   # Cambiar si se desea
HOTSPOT_IP       = "192.168.4.1"
HOTSPOT_CON_NAME = "AleBox-Hotspot"


def _run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


class HotspotManager:
    def __init__(self):
        self.active = False

    def start(self):
        """Activa el hotspot WiFi. Devuelve True si tuvo éxito."""
        print(f"  Activando hotspot '{HOTSPOT_SSID}'...")

        # Eliminar conexión previa si existe
        _run(["sudo", "nmcli", "connection", "delete", HOTSPOT_CON_NAME])

        result = _run([
            "sudo", "nmcli", "connection", "add",
            "type",        "wifi",
            "ifname",      "wlan0",
            "con-name",    HOTSPOT_CON_NAME,
            "autoconnect", "no",
            "ssid",        HOTSPOT_SSID,
            "mode",        "ap",
            "ipv4.method", "shared",
            "ipv4.addresses", f"{HOTSPOT_IP}/24",
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk",      HOTSPOT_PASSWORD,
        ])

        if result.returncode != 0:
            print(f"  Error al crear hotspot: {result.stderr.strip()}")
            return False

        result = _run([
            "sudo", "nmcli", "connection", "up", HOTSPOT_CON_NAME
        ])

        if result.returncode != 0:
            print(f"  Error al activar hotspot: {result.stderr.strip()}")
            return False

        time.sleep(2)  # dar tiempo a que la interfaz se levante
        self.active = True
        print(f"  ✅ Hotspot activo: '{HOTSPOT_SSID}' → {HOTSPOT_IP}")
        print(f"  Contraseña: {HOTSPOT_PASSWORD}")
        print(f"  Interfaz  : http://{HOTSPOT_IP}:8000")
        return True

    def stop(self):
        """Desactiva el hotspot."""
        if not self.active:
            return
        print("  Desactivando hotspot...")
        _run(["sudo", "nmcli", "connection", "down", HOTSPOT_CON_NAME])
        _run(["sudo", "nmcli", "connection", "delete", HOTSPOT_CON_NAME])
        self.active = False
        print("  Hotspot desactivado")
        time.sleep(1)  # dar tiempo a que wlan0 vuelva al estado normal
