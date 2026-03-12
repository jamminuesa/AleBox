#!/usr/bin/env python3
"""
KY040 - Clase para encoder rotativo KY-040
Compatible con Raspberry Pi OS moderno (Debian Trixie / kernel 6.x)

Requiere:
    python3-rpi-lgpio instalado a nivel sistema
    venv creado con --system-site-packages
"""

from gpiozero import RotaryEncoder, Button
from typing import Callable, Optional


class KY040:
    """
    Clase para manejar el encoder rotativo KY-040.

    Parámetros
    ----------
    clk : int
        Pin BCM de la señal CLK.
    dt : int
        Pin BCM de la señal DT.
    sw : int
        Pin BCM del pulsador SW.
    on_clockwise : Callable[[int], None], opcional
        Función llamada al girar en sentido horario.
        Recibe el valor actual del contador como argumento.
    on_counter_clockwise : Callable[[int], None], opcional
        Función llamada al girar en sentido antihorario.
        Recibe el valor actual del contador como argumento.
    on_press : Callable[[], None], opcional
        Función llamada al pulsar el botón (pulsación corta).
    on_hold : Callable[[], None], opcional
        Función llamada al mantener el botón pulsado.
    max_steps : int, opcional
        Límite superior del contador. None = sin límite.
    min_steps : int, opcional
        Límite inferior del contador. None = sin límite.
    hold_time : float, opcional
        Segundos que hay que mantener pulsado para activar on_hold (default: 1.0).
    bounce_time : float, opcional
        Tiempo de debounce del botón en segundos (default: 0.1).

    Ejemplo de uso
    --------------
    def subir(valor):
        print(f"Subiendo → {valor}")

    def bajar(valor):
        print(f"Bajando → {valor}")

    def pulsar():
        print("Botón pulsado")

    def mantener():
        print("Botón mantenido")

    encoder = KY040(
        clk=17, dt=27, sw=22,
        on_clockwise=subir,
        on_counter_clockwise=bajar,
        on_press=pulsar,
        on_hold=mantener,
        max_steps=10,
        min_steps=0
    )

    from signal import pause
    pause()
    """

    def __init__(
        self,
        clk: int,
        dt: int,
        sw: int,
        on_clockwise: Optional[Callable[[int], None]] = None,
        on_counter_clockwise: Optional[Callable[[int], None]] = None,
        on_press: Optional[Callable[[], None]] = None,
        on_hold: Optional[Callable[[], None]] = None,
        max_steps: Optional[int] = None,
        min_steps: Optional[int] = None,
        hold_time: float = 1.0,
        bounce_time: float = 0.1,
    ):
        self._on_clockwise = on_clockwise
        self._on_counter_clockwise = on_counter_clockwise
        self._on_press = on_press
        self._on_hold = on_hold
        self._max_steps = max_steps
        self._min_steps = min_steps

        # gpiozero usa max_steps=0 para indicar sin límite interno,
        # nosotros gestionamos los límites manualmente para tener min/max.
        self._encoder = RotaryEncoder(clk, dt, max_steps=0)
        self._encoder.when_rotated_clockwise = self._handle_clockwise
        self._encoder.when_rotated_counter_clockwise = self._handle_counter_clockwise

        self._button = Button(sw, pull_up=True, bounce_time=bounce_time, hold_time=hold_time)
        self._button.when_pressed = self._handle_press
        if on_hold:
            self._button.when_held = self._handle_hold

    # ── Propiedades públicas ────────────────────────────────────────────────

    @property
    def value(self) -> int:
        """Valor actual del contador."""
        return self._encoder.steps

    @value.setter
    def value(self, new_value: int):
        """Permite cambiar el contador desde fuera (ej: reset a 0)."""
        self._encoder.steps = new_value

    # ── Handlers internos ───────────────────────────────────────────────────

    def _handle_clockwise(self):
        if self._max_steps is not None and self._encoder.steps > self._max_steps:
            self._encoder.steps = self._max_steps
            return
        if self._on_clockwise:
            self._on_clockwise(self._encoder.steps)

    def _handle_counter_clockwise(self):
        if self._min_steps is not None and self._encoder.steps < self._min_steps:
            self._encoder.steps = self._min_steps
            return
        if self._on_counter_clockwise:
            self._on_counter_clockwise(self._encoder.steps)

    def _handle_press(self):
        # when_held y when_pressed se disparan juntos si se mantiene.
        # Ignoramos when_pressed si on_hold está definido y el botón se mantiene.
        # gpiozero ya diferencia entre ambos eventos de forma nativa.
        if self._on_press:
            self._on_press()

    def _handle_hold(self):
        if self._on_hold:
            self._on_hold()

    # ── Utilidades ──────────────────────────────────────────────────────────

    def reset(self):
        """Resetea el contador a 0 (o al mínimo si está definido)."""
        self._encoder.steps = self._min_steps if self._min_steps is not None else 0

    def close(self):
        """Libera los recursos GPIO. Llamar al terminar el programa."""
        self._encoder.close()
        self._button.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return (
            f"KY040(value={self.value}, "
            f"min={self._min_steps}, max={self._max_steps})"
        )
