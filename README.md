# 🎵 AleBox

🌐 [Versión en español disponible aquí → README.es.md](README.es.md)

A children's audio player based on Raspberry Pi Zero 2W and NFC tags. Bring a card close to the reader and the music starts. No screens, no complexity.

> **Note:** The web interface and system audio cues are currently in Spanish. If the project gains traction, multilingual support may be added in a future release.

> **License:** [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — Free for personal and educational use. Commercial use prohibited without the author's permission.

---

## 📋 Bill of Materials

| Component | Description | Qty |
|---|---|---|
| Raspberry Pi Zero 2W | Main board | 1 |
| microSD card | Minimum 8GB (class 10 recommended) | 1 |
| MAX98357A | I2S amplifier (3W, mono) | 1 |
| 4Ω 3W speaker | Compatible with MAX98357A | 1 |
| RC522 | SPI RFID/NFC reader | 1 |
| NFC tags | MIFARE tags for audio assignment | N |
| KY040 | Rotary encoder with push button (volume) | 1 |
| 4-pin DIP button 7mm | Control buttons | 5 |
| 5V/2A power supply | microUSB connector | 1 |
| Dupont cables | Female-to-female for connections | — |
| Enclosure | Builder's choice | 1 |

---

## ⚡ Wiring

### MAX98357A → Raspberry Pi (I2S)

| MAX98357A | GPIO | Physical pin |
|---|---|---|
| VIN | — | Pin 2 (5V) |
| GND | — | Pin 6 |
| BCLK | GPIO18 | Pin 12 |
| LRC | GPIO19 | Pin 35 |
| DIN | GPIO21 | Pin 40 |
| SD | GPIO24 | Pin 18 |
| GAIN | — | Pin 1 (3.3V → 9dB) |

> The SD pin controls mute in software. Connect GAIN to 3.3V for 9dB gain or leave floating for 6dB.

### RC522 RFID → Raspberry Pi (SPI)

| RC522 | GPIO | Physical pin |
|---|---|---|
| SDA | GPIO8 | Pin 24 |
| SCK | GPIO11 | Pin 23 |
| MOSI | GPIO10 | Pin 19 |
| MISO | GPIO9 | Pin 21 |
| RST | GPIO25 | Pin 22 |
| 3.3V | — | Pin 17 |
| GND | — | Pin 25 |

### KY040 Encoder → Raspberry Pi

| KY040 | GPIO | Physical pin |
|---|---|---|
| CLK | GPIO17 | Pin 11 |
| DT | GPIO27 | Pin 13 |
| SW | GPIO22 | Pin 15 |
| VCC | — | Pin 17 (3.3V) |
| GND | — | Pin 9 |

### Buttons → Raspberry Pi

> 4-pin DIP buttons have pins 1-2 bridged internally and pins 3-4 bridged internally. Connect pin 1 to GPIO and pin 3 to GND. Internal pull-up resistors are enabled in software. Buttons can share the GND pin on the RPi by soldering them together.

| Function | GPIO | Physical pin |
|---|---|---|
| Configuration mode | GPIO16 | Pin 36 |
| Power off | GPIO6 | Pin 31 |
| Forward / Next | GPIO26 | Pin 37 |
| Rewind / Previous | GPIO13 | Pin 33 |
| Auxiliary (save position) | GPIO5 | Pin 29 |

---

## 🗂️ Project structure

```
~/AleBox/
├── player.py           ← Main audio player
├── server.py           ← Web management server
├── hotspot.py          ← WiFi access point management
├── wifi.py             ← WiFi network management via SSH
├── setup.sh            ← Automated installation script
├── assignments.json    ← NFC → audio mappings (auto-generated)
├── positions.json      ← Saved positions per tag (auto-generated)
├── aux/
│   └── ky040.py        ← KY040 encoder class
├── audios/             ← Individual audio files
│   └── <playlist>/     ← Subfolders = playlists
├── sounds/
│   ├── hello/          ← Welcome audio files (one picked at random)
│   ├── goodbye/        ← Goodbye audio files (one picked at random)
│   ├── no_network.wav  ← Played when no network is available
│   └── configuration_mode.wav ← Played when entering config mode
├── web/
│   ├── index.html      ← Web management interface
│   └── fonts/          ← Local fonts (Fredoka One, Nunito)
└── tmp/                ← Temporary upload directory
```

---

## 🚀 Installation

### 1. Flash the microSD card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to install **Raspberry Pi OS Lite (64-bit)** based on Debian Trixie (no desktop). During the process, configure the username, password and WiFi network directly in the imager.

### 2. First boot and SSH access

Connect the RPi to your network, find its IP address and connect via SSH:

```bash
ssh alebox@<rpi-ip-address>
```

### 3. Clone or copy the project

```bash
cd ~
git clone https://github.com/your-username/alebox.git AleBox
cd AleBox
```

Alternatively, copy the files manually with `scp`.

### 4. Run the installation script

```bash
sudo bash setup.sh
```

The script automatically performs the following steps:

1. Updates the system packages
2. Installs dependencies (`vlc`, `python3-gpiozero`, `python3-rpi-lgpio`, `liblgpio-dev`, etc.)
3. Configures the I2S overlay for the MAX98357A in `/boot/firmware/config.txt`
4. Enables SPI for the RC522
5. Configures `softvol` in ALSA for software volume control
6. Creates a Python virtual environment and installs libraries (`python-vlc`, `flask`, `mfrc522`, `gpiozero`, `rpi-lgpio`)
7. Creates the required folders (`audios/`, `tmp/`)
8. Installs and enables the `systemd` service for autostart on boot

When finished, the script asks whether to reboot. Answer yes.

### 5. Required sudo permissions

To allow the user to shut down the system and manage networks without a password:

```bash
sudo visudo
```

Add at the end:

```
alebox ALL=(ALL) NOPASSWD: /sbin/poweroff
alebox ALL=(ALL) NOPASSWD: /usr/bin/nmcli
```

### 6. Add system sounds

Create welcome and goodbye audio files in WAV, MP3, OGG or M4A format:

```bash
mkdir -p ~/AleBox/sounds/hello ~/AleBox/sounds/goodbye
# Copy your audio files here
```

### 7. Verify everything is working

```bash
sudo systemctl status alebox
journalctl -u alebox -f
```

---

## 🎮 Usage

### Physical controls

| Control | Short press | Long press (>1s) |
|---|---|---|
| **Encoder (turn)** | Volume up/down | — |
| **Encoder (button)** | Play / Pause | Go to start of track |
| **Next button** | Skip forward 30 seconds | Next track |
| **Previous button** | Skip back 30 seconds | Start of track / Previous track* |
| **Auxiliary button** | Save position | Delete saved position |
| **Config button** | Enter/exit configuration mode | — |
| **Power button** | Safe shutdown | — |

> *Long press on the previous button goes to the previous track if less than 10 seconds have elapsed in the current track, or to the start of the track otherwise.

### NFC tags

Bring any MIFARE NFC tag close to the reader to play its assigned audio. If the tag has no assignment, nothing happens. To assign tags, enter configuration mode.

### Configuration mode

Press the configuration button. If a WiFi network is available, the web server starts and you can access the interface from a browser at `http://<rpi-ip>:8000`. If there is no network, the RPi automatically creates a hotspot called **AleBox-Setup** (password: `alebox123`) and the server is available at `http://192.168.4.1:8000`.

From the web interface you can:
- Upload individual audio files (MP3, WAV, OGG, M4A)
- Upload full folders as playlists (ZIP)
- Assign NFC tags to audio files or playlists
- Choose random or alphabetical order for playlists
- Manage all existing assignments
- Return to player mode using the web button or the physical button

### WiFi management via SSH

```bash
python3 ~/AleBox/wifi.py status    # current connection status
python3 ~/AleBox/wifi.py list      # saved networks
python3 ~/AleBox/wifi.py scan      # networks visible in the area
python3 ~/AleBox/wifi.py add       # add a new network (interactive)
python3 ~/AleBox/wifi.py delete    # remove a saved network (interactive)
```

---

## 🔧 Configuration

Main parameters at the top of `player.py`:

```python
VOLUME        = 48    # Initial volume (0-100)
VOLUME_STEP   = 2     # Volume change per encoder tick
VOLUME_MAX    = 80    # Maximum volume (adjust to avoid distortion)
SKIP_SECONDS  = 30    # Seconds to skip forward/back
HOLD_TIME     = 1.0   # Seconds to trigger a long press
PREV_RESTART  = 10    # Seconds threshold to go to previous track
```

Hotspot parameters in `hotspot.py`:

```python
HOTSPOT_SSID     = "AleBox-Setup"
HOTSPOT_PASSWORD = "alebox123"
HOTSPOT_IP       = "192.168.4.1"
```

---

## 📄 License

This project is licensed under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**.

You are free to:
- ✅ Use, copy and distribute the project freely
- ✅ Modify and adapt it to your needs
- ✅ Share modified versions

Under the following terms:
- 📌 Give appropriate credit to the original author
- 🚫 Do not use it for commercial purposes

For commercial use, please contact the author to obtain permission.

[Read the full license text](https://creativecommons.org/licenses/by-nc/4.0/legalcode)
