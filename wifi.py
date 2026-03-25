#!/usr/bin/env python3
"""
wifi.py - Gestión de redes WiFi para AleBox
Usa nmcli (NetworkManager) para listar, añadir y eliminar redes.

Uso:
  python3 wifi.py list       → redes guardadas
  python3 wifi.py scan       → redes visibles en el entorno
  python3 wifi.py add        → añadir nueva red (interactivo)
  python3 wifi.py delete     → eliminar una red guardada (interactivo)
  python3 wifi.py status     → estado actual de la conexión
"""

import subprocess
import sys
import getpass


def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  Error: {result.stderr.strip()}")
        return None
    return result.stdout.strip()


def status():
    print("\n── Conexión actual ─────────────────────")
    out = run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"])
    if not out:
        return
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] in ("wlan0", "wlan1"):
            device, state, connection = parts[0], parts[1], parts[2]
            if state == "connected":
                # Obtener IP
                ip = run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", device])
                ip_addr = ip.split(":")[1].split("/")[0] if ip and ":" in ip else "desconocida"
                print(f"  ✅ Conectado a: {connection}")
                print(f"  📡 Interfaz   : {device}")
                print(f"  🌐 IP         : {ip_addr}")
            else:
                print(f"  ❌ {device}: {state}")


def list_saved():
    print("\n── Redes WiFi guardadas ────────────────")
    out = run(["nmcli", "-t", "-f", "NAME,TYPE,TIMESTAMP-REAL", "connection", "show"])
    if not out:
        print("  Sin redes guardadas")
        return []

    redes = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and "wireless" in parts[1]:
            nombre = parts[0]
            fecha  = parts[2] if len(parts) > 2 else "—"
            redes.append(nombre)
            print(f"  [{len(redes)}] {nombre}  (añadida: {fecha})")

    if not redes:
        print("  Sin redes WiFi guardadas")
    return redes


def scan():
    print("\n── Escaneando redes disponibles ────────")
    print("  (esto puede tardar unos segundos...)")
    # Forzar rescan
    run(["nmcli", "device", "wifi", "rescan"], check=False)
    import time; time.sleep(2)

    out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"])
    if not out:
        print("  No se encontraron redes")
        return

    vistas = set()
    redes  = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        ssid     = parts[0].strip()
        signal   = parts[1]
        security = parts[2] if parts[2] else "Abierta"
        in_use   = "✅ " if parts[3] == "*" else "   "
        if ssid and ssid not in vistas:
            vistas.add(ssid)
            redes.append(ssid)
            bars = "▓" * (int(signal) // 20) + "░" * (5 - int(signal) // 20)
            print(f"  {in_use}[{len(redes):2}] {ssid:<32} {bars} {signal}%  {security}")

    return redes


def add():
    print("\n── Añadir red WiFi ─────────────────────")

    # Mostrar redes disponibles para facilitar
    redes = scan()
    print()

    ssid = input("  SSID (nombre de la red): ").strip()
    if not ssid:
        print("  Cancelado")
        return

    # Comprobar si ya existe
    saved = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    if saved and ssid in saved.splitlines():
        print(f"  ⚠️  La red '{ssid}' ya está guardada")
        sobreescribir = input("  ¿Sobreescribir? (s/n): ").strip().lower()
        if sobreescribir != 's':
            print("  Cancelado")
            return
        run(["sudo", "nmcli", "connection", "delete", ssid], check=False)

    password = getpass.getpass(f"  Contraseña para '{ssid}' (vacío si es abierta): ")

    print(f"  Conectando a '{ssid}'...")
    if password:
        result = run([
            "sudo", "nmcli", "device", "wifi", "connect", ssid,
            "password", password
        ])
    else:
        result = run(["sudo", "nmcli", "device", "wifi", "connect", ssid])

    if result is not None:
        print(f"  ✅ Conectado y red guardada: {ssid}")
    else:
        print(f"  ❌ No se pudo conectar a '{ssid}'")
        print("     Comprueba que el SSID y la contraseña son correctos")


def delete():
    print("\n── Eliminar red WiFi guardada ──────────")
    redes = list_saved()
    if not redes:
        return

    print()
    try:
        opcion = input("  Número de la red a eliminar (0 para cancelar): ").strip()
        idx = int(opcion)
    except ValueError:
        print("  Cancelado")
        return

    if idx == 0:
        print("  Cancelado")
        return

    if idx < 1 or idx > len(redes):
        print("  Número no válido")
        return

    nombre = redes[idx - 1]
    confirmar = input(f"  ¿Eliminar '{nombre}'? (s/n): ").strip().lower()
    if confirmar != 's':
        print("  Cancelado")
        return

    result = run(["sudo", "nmcli", "connection", "delete", nombre])
    if result is not None:
        print(f"  ✅ Red '{nombre}' eliminada")
    else:
        print(f"  ❌ No se pudo eliminar '{nombre}'")


def ayuda():
    print(__doc__)


COMANDOS = {
    "list":   list_saved,
    "scan":   scan,
    "add":    add,
    "delete": delete,
    "status": status,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDOS:
        ayuda()
        print("Comandos disponibles:", ", ".join(COMANDOS.keys()))
        sys.exit(1)

    COMANDOS[sys.argv[1]]()
    print()
