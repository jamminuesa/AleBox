#!/usr/bin/env python3
"""
Test de la clase KY040
"""

import os
#os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"

from aux.ky040 import KY040
from signal import pause

# ── Define tus callbacks ────────────────────────────────────────────────────

def subir(valor: int):
    print(f"  ↻ HORARIO        → contador: {valor}")

def bajar(valor: int):
    print(f"  ↺ ANTIHORARIO    → contador: {valor}")

def pulsar():
    print("  ● PULSADO        (pulsación corta)")

def mantener():
    print("  ⬤ MANTENIDO      (hold)")

# ── Instancia con context manager (libera GPIO automáticamente) ─────────────

print("=" * 50)
print("  KY040 class test  |  Ctrl+C para salir")
print("=" * 50)
print("  Rango: 0 - 10")
print("  Hold: 1 segundo")
print("=" * 50)

with KY040(
    clk=17, dt=27, sw=22,
    on_clockwise=subir,
    on_counter_clockwise=bajar,
    on_press=pulsar,
    on_hold=mantener,
    #max_steps=0,
    #min_steps=0,
    hold_time=1.0,
) as encoder:
    try:
        pause()
    except KeyboardInterrupt:
        print(f"\nValor final: {encoder.value}")
