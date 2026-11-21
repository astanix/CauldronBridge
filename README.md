# CauldronBridge — M110 BLE to ESC/POS Thermal Printer Bridge

Turn a Raspberry Pi into a **Phomemo M110** Bluetooth Low Energy (BLE) printer so the **Cauldron** mobile app can print to a network-connected ESC/POS thermal receipt printer (such as a Seiko RP-D10) over TCP port `9100`.

## How It Works

1. **Emulates an `M110` BLE Peripheral**: Uses `bluezero` to advertise your Raspberry Pi's Bluetooth adapter as `M110` and receive BLE write chunks from Cauldron.
2. **Extracts & Auto-Crops Raster Data**: Pulls `GS v 0` (`1d 76 30`) bitmap rows from the stream and trims blank leading/trailing rows while keeping a small padding margin.
3. **Scales & Darkens for 80mm Paper**: Resizes 384px-wide (48-byte) M110 graphics by `1.5x` to `576px` (72-byte) using `Pillow` and applies a brightness threshold so stippled source images print with strong black coverage.
4. **Streams Smoothly Over TCP**: Sends one `GS v 0` header for the full image and streams 2 KB chunks with `TCP_NODELAY` so fast thermal printers feed continuously without motor stutter, followed by a line feed and partial cut.

---

## What You Need to Change for Your Printer

Before enabling the `systemd` service, update these settings for **your** setup:

1. **Your Printer's IP Address (`--ip`)**: Replace `192.168.50.199` in `cauldron-bridge.service` (or pass `--ip YOUR_PRINTER_IP` on the command line) with the static or DHCP-reserved IP address of your network ESC/POS printer (raw port `9100` by default).
2. **Install Location (`/opt/CauldronBridge`)**: `systemd` does not expand `~` or `$HOME`, so the service file uses `/opt/CauldronBridge` as a user-agnostic system path. If you clone the repo into a different folder, update `WorkingDirectory` and `ExecStart` in `cauldron-bridge.service` to match.
3. **Optional Print Tuning Flags**:
   - `--darkness 185` (`0`–`255`): Raise toward `210` for heavier black ink coverage, or lower toward `160` if shaded areas look too dark.
   - `--padding 4`: Number of blank lines kept above and below cropped artwork.
   - `--cut-feed 3`: Number of lines fed past the cutter blade before cutting.
   - `--mac XX:XX:XX:XX:XX:XX`: Only needed if auto-detection picks the wrong Bluetooth adapter.

---

## Quick Start

### 1. Install Dependencies & Clone Repo into `/opt/CauldronBridge`

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dbus libglib2.0-dev libjpeg-dev zlib1g-dev rfkill

cd /opt
sudo git clone https://github.com/astanix/CauldronBridge.git
sudo chown -R $USER:$USER /opt/CauldronBridge
cd /opt/CauldronBridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Test Manually with Your Printer's IP

```bash
sudo venv/bin/python printer_emulator.py --ip YOUR_PRINTER_IP
```

On your phone, toggle Bluetooth off/on if needed to clear stale BLE caches, open **Cauldron**, connect to **M110**, and send a test print. Press `Ctrl + C` when finished testing.

### 3. Install & Enable the Boot Service (`systemd`)

Enable BlueZ `AutoEnable` so Bluetooth powers on automatically at boot:

```bash
sudo sed -i 's/^#*AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
```

Update `--ip` in `cauldron-bridge.service` to match your printer's IP address, then install and start the service:

```bash
sudo cp cauldron-bridge.service /etc/systemd/system/cauldron-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now cauldron-bridge.service
```

Check that it is running and advertising:

```bash
sudo systemctl status cauldron-bridge.service --no-pager
bluetoothctl show | grep -E "Alias|Powered|ActiveInstances"
```

---

## Useful Commands

- **Watch live print logs**: `sudo journalctl -u cauldron-bridge.service -f`
- **Restart after editing config or code**: `sudo systemctl restart cauldron-bridge.service`
- **Stop background service**: `sudo systemctl stop cauldron-bridge.service`
