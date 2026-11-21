#!/usr/bin/env python3
import argparse
import glob
import socket
import threading
import time
from bluezero import peripheral
from PIL import Image


def get_default_adapter_mac():
    """Auto-detects the primary Bluetooth adapter MAC address on Linux."""
    paths = sorted(glob.glob("/sys/class/bluetooth/hci*/address"))
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                mac = f.read().strip().upper()
                if mac and mac != "00:00:00:00:00:00":
                    return mac
        except OSError:
            continue
    raise RuntimeError("No active Bluetooth adapter found under /sys/class/bluetooth/.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Cauldron M110 BLE Bridge to Network ESC/POS Thermal Printer"
    )
    # CHANGE THIS DEFAULT IP TO MATCH YOUR NETWORK THERMAL PRINTER
    parser.add_argument(
        "--ip",
        default="192.168.50.199",
        help="Target ESC/POS receipt printer IP address (default: 192.168.50.199)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9100,
        help="Target ESC/POS printer raw TCP port (default: 9100)",
    )
    parser.add_argument(
        "--mac",
        default=None,
        help="Bluetooth adapter MAC address (auto-detected if omitted)",
    )
    parser.add_argument(
        "--darkness",
        type=int,
        default=185,
        help="Post-resize darkness threshold from 0-255; higher = darker (default: 185)",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=4,
        help="Blank dot-lines kept above and below auto-cropped content (default: 4)",
    )
    parser.add_argument(
        "--cut-feed",
        type=int,
        default=3,
        help="Lines fed past cutter blade before partial cut (default: 3)",
    )
    return parser.parse_args()


ARGS = parse_args()
PRINTER_NAME = "M110"
ADAPTER_ADDR = ARGS.mac or get_default_adapter_mac()
PRINTER_IP = ARGS.ip
PRINTER_PORT = ARGS.port
DARKNESS_THRESHOLD = max(0, min(255, ARGS.darkness))
CROP_PADDING_LINES = max(0, ARGS.padding)
CUT_FEED_LINES = max(0, min(25, ARGS.cut_feed))

print_buffer = bytearray()
timer = None
lock = threading.Lock()


def crop_blank_lines(width, bitmap, pad_lines=CROP_PADDING_LINES):
    """Removes empty white rows (0x00) from top and bottom while keeping a small border."""
    total_lines = len(bitmap) // width
    if total_lines == 0:
        return bitmap

    blank_row = b"\x00" * width

    top = 0
    while top < total_lines and bitmap[top * width : (top + 1) * width] == blank_row:
        top += 1

    if top == total_lines:
        return bitmap

    bottom = total_lines - 1
    while bottom > top and bitmap[bottom * width : (bottom + 1) * width] == blank_row:
        bottom -= 1

    top_padded = max(0, top - pad_lines)
    bottom_padded = min(total_lines - 1, bottom + pad_lines)

    cropped_lines = (bottom_padded - top_padded) + 1
    print(f"[*] Auto-cropped {total_lines - cropped_lines} blank lines")
    return bytearray(bitmap[top_padded * width : (bottom_padded + 1) * width])


def scale_bitmap_15x_dark(width, bitmap):
    """Scales 384px (48-byte) M110 bitmap 1.5x to 576px (72-byte) with thresholded darkness."""
    total_lines = len(bitmap) // width
    px_w = width * 8
    new_px_w = int(px_w * 1.5)
    new_px_h = int(total_lines * 1.5)

    # Convert ESC/POS bits (1=black) to PIL '1' mode (0=black, 255=white), then grayscale
    inverted = bytes(b ^ 0xFF for b in bitmap)
    img = Image.frombytes("1", (px_w, total_lines), inverted).convert("L")
    img_resized = img.resize((new_px_w, new_px_h), Image.Resampling.LANCZOS)

    lut = [0 if i < DARKNESS_THRESHOLD else 255 for i in range(256)]
    img_1bit = img_resized.point(lut, mode="1")

    re_inverted = bytes(b ^ 0xFF for b in img_1bit.tobytes())
    return new_px_w // 8, bytearray(re_inverted)


def extract_all_rasters(raw_data):
    """Extracts and combines GS v 0 (1d 76 30) raster blocks from the M110 stream."""
    pos = 0
    total_width = None
    combined_bitmap = bytearray()

    while True:
        idx = raw_data.find(b"\x1d\x76\x30", pos)
        if idx == -1 or idx + 8 > len(raw_data):
            break

        mode = raw_data[idx + 3]
        w = raw_data[idx + 4] + (raw_data[idx + 5] << 8)
        h = raw_data[idx + 6] + (raw_data[idx + 7] << 8)

        if mode > 3 or w == 0 or w > 128 or h == 0 or h > 4000:
            pos = idx + 3
            continue

        expected = w * h
        start = idx + 8
        end = start + expected
        chunk = raw_data[start:end]

        if len(chunk) < expected:
            chunk = chunk + (b"\x00" * (expected - len(chunk)))

        if total_width is None:
            total_width = w
        if w == total_width:
            combined_bitmap.extend(chunk)

        pos = end

    return total_width, combined_bitmap


def flush_buffer():
    global print_buffer
    with lock:
        if not print_buffer:
            return
        raw_data = bytes(print_buffer)
        print_buffer.clear()

    print(f"\n[+] Stream complete! Captured {len(raw_data)} bytes.")

    width, bitmap = extract_all_rasters(raw_data)
    if not width or not bitmap:
        print("[!] No valid GS v 0 raster found in stream.")
        return

    bitmap = crop_blank_lines(width, bitmap)
    width, bitmap = scale_bitmap_15x_dark(width, bitmap)
    total_lines = len(bitmap) // width
    print(f"[*] Output bitmap: {width * 8}x{total_lines} px -> {PRINTER_IP}:{PRINTER_PORT}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10.0)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((PRINTER_IP, PRINTER_PORT))

            # Initialize, center-align, and send one GS v 0 header for smooth continuous feed
            single_header = (
                b"\x1b\x40\x1b\x61\x01\x1d\x76\x30\x00"
                + bytes(
                    [
                        width & 0xFF,
                        (width >> 8) & 0xFF,
                        total_lines & 0xFF,
                        (total_lines >> 8) & 0xFF,
                    ]
                )
            )
            s.sendall(single_header)

            chunk_size = 2048
            for i in range(0, len(bitmap), chunk_size):
                s.sendall(bitmap[i : i + chunk_size])
                time.sleep(0.012)

            time.sleep(0.35)
            cut_cmd = b"\x1b\x40\x1b\x64" + bytes([CUT_FEED_LINES]) + b"\x1d\x56\x01"
            s.sendall(cut_cmd)
            time.sleep(0.3)

        print("[+] Print job and cut sent successfully.\n")
    except Exception as e:
        print(f"[-] Network forwarding error: {e}")


def write_callback(value, *args):
    global print_buffer, timer
    chunk = bytes(value)
    with lock:
        print_buffer.extend(chunk)
        print(f"-> RX {len(chunk)} bytes (Total: {len(print_buffer)})")
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(0.8, flush_buffer)
        timer.start()


def read_status_callback(*args):
    return [0x00, 0x01, 0x02, 0x00]


def main():
    app = peripheral.Peripheral(
        adapter_address=ADAPTER_ADDR,
        local_name=PRINTER_NAME,
        appearance=0x0381,
    )

    app.add_service(srv_id=1, uuid="0000ff00-0000-1000-8000-00805f9b34fb", primary=True)

    app.add_characteristic(
        srv_id=1,
        chr_id=1,
        uuid="0000ff01-0000-1000-8000-00805f9b34fb",
        value=[],
        notifying=False,
        flags=["write", "write-without-response"],
        write_callback=write_callback,
    )

    app.add_characteristic(
        srv_id=1,
        chr_id=2,
        uuid="0000ff02-0000-1000-8000-00805f9b34fb",
        value=[],
        notifying=False,
        flags=["write", "write-without-response"],
        write_callback=write_callback,
    )

    app.add_characteristic(
        srv_id=1,
        chr_id=3,
        uuid="0000ff03-0000-1000-8000-00805f9b34fb",
        value=[0x00],
        notifying=True,
        flags=["read", "notify"],
        read_callback=read_status_callback,
    )

    print(
        f"Starting Cauldron M110 BLE Bridge ({ADAPTER_ADDR}) -> "
        f"{PRINTER_IP}:{PRINTER_PORT} [darkness={DARKNESS_THRESHOLD}, padding={CROP_PADDING_LINES}]"
    )
    app.publish()


if __name__ == "__main__":
    main()
