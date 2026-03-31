# 🎵 AleBox

🌐 [English version available here → README.md](README.md)

Un reproductor de audio para niños basado en Raspberry Pi Zero 2W y etiquetas NFC. Acerca una tarjeta al lector y empieza la música. Sin pantallas, sin complicaciones.

> **Licencia:** [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — Uso personal y educativo libre. Uso comercial prohibido sin permiso del autor.

---

## 📋 Bill of Materials

| Componente | Descripción | Cantidad |
|---|---|---|
| Raspberry Pi Zero 2W | Placa principal | 1 |
| Tarjeta microSD | Mínimo 8GB (clase 10 recomendada) | 1 |
| MAX98357A | Amplificador I2S (3W, mono) | 1 |
| Altavoz 4Ω 3W | Compatible con MAX98357A | 1 |
| RC522 | Lector RFID/NFC por SPI | 1 |
| Etiquetas NFC | Tags para asignar audios | N |
| KY040 | Encoder rotativo con pulsador (volumen) | 1 |
| Botón DIP 4 patas 7 mm | Botones de control | 5 |
| Fuente de alimentación 5V/2A | Con conector microUSB | 1 |
| Cables Dupont | Hembra-hembra para conexiones | — |
| Caja/chasis | A elección del constructor | 1 |

---

## ⚡ Conexiones eléctricas

### MAX98357A → Raspberry Pi (I2S)

| MAX98357A | GPIO | Pin físico |
|---|---|---|
| VIN | — | Pin 2 (5V) |
| GND | — | Pin 6 |
| BCLK | GPIO18 | Pin 12 |
| LRC | GPIO19 | Pin 35 |
| DIN | GPIO21 | Pin 40 |
| SD | GPIO24 | Pin 18 |
| GAIN | — | Pin 1 (3.3V → 9dB) |

> El pin SD controla el mute por software. Conectar GAIN a 3.3V para ganancia de 9dB o dejarlo flotante para 6dB.

### RC522 RFID → Raspberry Pi (SPI)

| RC522 | GPIO | Pin físico |
|---|---|---|
| SDA | GPIO8 | Pin 24 |
| SCK | GPIO11 | Pin 23 |
| MOSI | GPIO10 | Pin 19 |
| MISO | GPIO9 | Pin 21 |
| RST | GPIO25 | Pin 22 |
| 3.3V | — | Pin 17 |
| GND | — | Pin 25 |

### KY040 Encoder → Raspberry Pi

| KY040 | GPIO | Pin físico |
|---|---|---|
| CLK | GPIO17 | Pin 11 |
| DT | GPIO27 | Pin 13 |
| SW | GPIO22 | Pin 15 |
| VCC | — | Pin 17 (3.3V) |
| GND | — | Pin 9 |

### Botones → Raspberry Pi

> Los botones DIP de 4 patas tienen patas 1-2 unidas y patas 3-4 unidas. Conectar pata 1 al GPIO y pata 3 a GND. El pull-up interno está habilitado por software. Soldar botones entre si para que compartan el pin de GND en la RPi

| Función | GPIO | Pin físico |
|---|---|---|
| Modo configuración | GPIO16 | Pin 36 |
| Apagado | GPIO6 | Pin 31 |
| Avanzar / Siguiente | GPIO26 | Pin 37 |
| Retroceder / Anterior | GPIO13 | Pin 33 |
| Auxiliar (guardar posición) | GPIO5 | Pin 29 |

---

## 🗂️ Estructura del proyecto

```
~/FaPi/
├── player.py           ← Reproductor principal
├── server.py           ← Servidor web de gestión
├── hotspot.py          ← Gestión del punto de acceso WiFi
├── wifi.py             ← Gestión de redes WiFi por SSH
├── setup.sh            ← Script de instalación automática
├── assignments.json    ← Asignaciones NFC → audio (auto-generado)
├── positions.json      ← Posiciones guardadas por tag (auto-generado)
├── aux/
│   └── ky040.py        ← Clase para el encoder KY040
├── audios/             ← Archivos de audio individuales
│   └── <playlist>/     ← Subcarpetas = listas de reproducción
├── sounds/
│   ├── hello/          ← Audios de bienvenida (se elige uno al azar)
│   ├── goodbye/        ← Audios de despedida (se elige uno al azar)
│   ├── no_network.wav  ← Sonido cuando no hay red
│   └── configuration_mode.wav ← Sonido al entrar en modo config
├── web/
│   ├── index.html      ← Interfaz web de gestión
│   └── fonts/          ← Fuentes locales (Fredoka One, Nunito)
└── tmp/                ← Directorio temporal para subidas
```

---

## 🚀 Instalación

### 1. Flashear la tarjeta microSD

Usa [Raspberry Pi Imager](https://www.raspberrypi.com/software/) para instalar **Raspberry Pi OS Lite (64-bit)** basado en Debian Trixie, versión sin escritorio. Durante el proceso configura el nombre de usuario, contraseña y red WiFi desde el propio imager.

### 2. Primer arranque y acceso

Conecta la RPi a la red, localiza su IP y accede por SSH:

```bash
ssh alebox(o el usuario que hayas puesto)@<ip-de-la-rpi>
```

### 3. Clonar o copiar el proyecto

```bash
cd ~
git clone https://github.com/tu-usuario/alebox.git AleBox
cd AleBox
```

O copia los archivos manualmente con `scp`.

### 4. Ejecutar el script de instalación

```bash
sudo bash setup.sh
```

El script realiza automáticamente los siguientes pasos:

1. Actualiza el sistema
2. Instala dependencias (`vlc`, `python3-gpiozero`, `python3-rpi-lgpio`, `liblgpio-dev`, etc.)
3. Configura el overlay I2S para el MAX98357A en `/boot/firmware/config.txt`
4. Habilita SPI para el RC522
5. Configura `softvol` en ALSA para control de volumen por software
6. Crea el entorno virtual Python e instala las librerías (`python-vlc`, `flask`, `mfrc522`, `gpiozero`, `rpi-lgpio`)
7. Crea las carpetas necesarias (`audios/`, `tmp/`)
8. Instala y habilita el servicio `systemd` para arranque automático

Al terminar, el script pregunta si reiniciar. Di que sí.

### 5. Permisos sudo necesarios

Para que el usuario pueda apagar el sistema y gestionar redes sin contraseña:

```bash
sudo visudo
```

Añadir al final:

```
alebox ALL=(ALL) NOPASSWD: /sbin/poweroff
alebox ALL=(ALL) NOPASSWD: /usr/bin/nmcli
```

### 6. Añadir los sonidos del sistema

Crea los audios de bienvenida y despedida en formato WAV, MP3, OGG o M4A, o usa los del proyecto:

```bash
mkdir -p ~/AleBox/sounds/hello ~/AleBox/sounds/goodbye
# Copia tus archivos de audio aquí
```

### 7. Verificar que funciona

```bash
sudo systemctl status alebox
journalctl -u alebox -f
```

---

## 🎮 Uso

### Controles físicos

| Control | Acción corta | Acción larga (>1s) |
|---|---|---|
| **Encoder (giro)** | Subir/bajar volumen | — |
| **Encoder (botón)** | Play / Pausa | Ir al inicio de la pista |
| **Botón Siguiente** | Avanzar 30 segundos | Siguiente pista |
| **Botón Anterior** | Retroceder 30 segundos | Inicio de pista / Pista anterior* |
| **Botón Auxiliar** | Guardar posición | Borrar posición guardada |
| **Botón Config** | Entrar/salir modo configuración | — |
| **Botón Power** | Apagado seguro | — |

> *El botón anterior con pulsación larga va a la pista anterior si llevamos menos de 10 segundos en la pista actual, o al inicio de la pista si llevamos más.

### Tags NFC

Acerca cualquier etiqueta NFC MIFARE al lector para reproducir el audio asignado. Si la etiqueta no tiene ningún audio asignado, no ocurre nada. Para asignar etiquetas, entra en modo configuración.

### Modo configuración

Pulsa el botón de configuración. Si hay red WiFi disponible, se lanza el servidor web y puedes acceder desde el navegador a `http://<ip-de-la-rpi>:8000`. Si no hay red, la RPi crea automáticamente un punto de acceso llamado **AleBox-Setup** (contraseña: `alebox123`) y el servidor es accesible en `http://192.168.4.1:8000`.

Desde la interfaz web puedes:
- Subir archivos de audio individuales (MP3, WAV, OGG, M4A)
- Subir carpetas completas como listas de reproducción (ZIP)
- Asignar etiquetas NFC a audios o listas
- Elegir orden aleatorio u ordenado para las listas
- Gestionar todas las asignaciones existentes
- Volver al modo reproductor con el botón de la web o el botón físico

### Gestión de WiFi por SSH

```bash
python3 ~/AleBox/wifi.py status    # estado de la conexión actual
python3 ~/AleBox/wifi.py list      # redes guardadas
python3 ~/AleBox/wifi.py scan      # redes disponibles en el entorno
python3 ~/AleBox/wifi.py add       # añadir nueva red (interactivo)
python3 ~/AleBox/wifi.py delete    # eliminar una red guardada (interactivo)
```

---

## 🔧 Configuración

Los parámetros principales están al inicio de `player.py`:

```python
VOLUME        = 48    # Volumen inicial (0-100)
VOLUME_STEP   = 2     # Cambio por tick del encoder
VOLUME_MAX    = 80    # Volumen máximo (ajustar para evitar distorsión)
SKIP_SECONDS  = 30    # Segundos de avance/retroceso rápido
HOLD_TIME     = 1.0   # Segundos para considerar pulsación larga
PREV_RESTART  = 10    # Segundos al inicio para ir a pista anterior
```

Los parámetros del hotspot están en `hotspot.py`:

```python
HOTSPOT_SSID     = "AleBox-Setup"
HOTSPOT_PASSWORD = "alebox123"
HOTSPOT_IP       = "192.168.4.1"
```

---

## 📄 Licencia

Este proyecto está bajo la licencia **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**.

Esto significa que puedes:
- ✅ Usar, copiar y distribuir el proyecto libremente
- ✅ Modificarlo y adaptarlo a tus necesidades
- ✅ Compartir las versiones modificadas

Siempre que:
- 📌 Des crédito al autor original
- 🚫 No lo uses con fines comerciales

Para uso comercial, contacta con el autor para obtener permiso.

[Ver texto completo de la licencia](https://creativecommons.org/licenses/by-nc/4.0/legalcode)
