# Cauldron M110 BLE to ESC/POS Thermal Printer Bridge

Turn a Raspberry Pi into a **Phomemo M110** Bluetooth Low Energy (BLE) printer so the **Cauldron** mobile app can print to a network-connected ESC/POS thermal receipt printer (such as a Seiko RP-D10) over TCP port `9100`.

## How It Works

1. **Emulates an `M110` BLE Peripheral**: Uses `bluezero` to advertise your Raspberry Pi's Bluetooth adapter as `M110` and receive BLE write chunks from Cauldron.
2. **Extracts & Auto-Crops Raster Data**: Pulls `GS v 0` (`1d 76 30`) bitmap rows from the stream and trims blank leading/trailing rows while keeping a small padding margin.
3. **Scales & Darkens for 80mm Paper**: Resizes 384px-wide (48-byte) M110 graphics by `1.5x` to `576px` (72-byte) using `Pillow` and applies a brightness threshold so stippled source images print with strong black coverage.
4. **Streams Smoothly Over TCP**: Sends one `GS v 0` header for the full image and streams 2 KB chunks with `TCP_NODELAY` so fast thermal printers feed continuously without motor stutter, followed by a line feed and partial cut.

---

## What You Need to Change for Your Printer

Before running the bridge or enabling the `systemd` service, update these settings for **your** setup:

1. **Your Printer's IP Address (`--ip`)**: Replace `192.168.50.199` with the static or DHCP-reserved IP address of your network ESC/POS printer (raw port `9100` by default).
2. **Folder & User Paths (in `cauldron-bridge.service`)**: If you clone the repo somewhere other than `/home/astanix/cauldron-m110-escpos-bridge`, update `WorkingDirectory` and `ExecStart` in `cauldron-bridge.service` to match your path.
3. **Optional Print Tuning Flags**:
   - `--darkness 185` (`0`–`255`): Raise toward `210` for heavier black ink coverage, or lower toward `160` if shaded areas look too dark.
   - `--padding 4`: Number of blank lines kept above and below cropped artwork.
   - `--cut-feed 3`: Number of lines fed past the cutter blade before cutting.
   - `--mac XX:XX:XX:XX:XX:XX`: Only needed if auto-detection picks the wrong Bluetooth adapter.

---

## Quick Start

### 1. Install Dependencies & Clone Repo

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dbus libglib2.0-dev libjpeg-dev zlib1g-dev rfkill

git clone [https://github.com/YOUR_USERNAME/cauldron-m110-escpos-bridge.git](https://github.com/YOUR_USERNAME/cauldron-m110-escpos-bridge.git)
cd cauldron-m110-escpos-bridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
