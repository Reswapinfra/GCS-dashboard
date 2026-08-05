#!/usr/bin/env python3
"""
Reswap — Arm link test harness
Talks to reswap_arm_firmware.ino over USB serial and asserts that the firmware
speaks the same protocol the GCS expects. Run this BEFORE trusting the GCS UI:
if these pass, the contract is sound and any remaining problem is mechanical.

Setup:
    pip install pyserial
    # plug in the Arduino, close the Arduino IDE Serial Monitor (it locks the port)
    python test_arm_link.py                 # auto-detect port
    python test_arm_link.py --port COM5     # or name it explicitly
    python test_arm_link.py --list          # just list ports and exit

Note: tests T5/T6 physically move the servos. Keep the arm clear, or detach the
servo horns for a dry electrical test.
"""
import sys, time, argparse

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial not installed. Run:  pip install pyserial")

BAUD = 115200
passed = failed = 0

def find_port():
    ports = list(list_ports.comports())
    for p in ports:
        d = (p.description or "").lower()
        if any(k in d for k in ("arduino", "usb serial", "ch340", "wchusb", "usbmodem", "usbserial")):
            return p.device
    return ports[0].device if ports else None

def drain(ser, secs=0.4):
    """Collect every line the board emits for `secs`."""
    end = time.time() + secs
    lines = []
    while time.time() < end:
        raw = ser.readline().decode(errors="replace").strip()
        if raw:
            lines.append(raw)
    return lines

def cmd(ser, text, wait=0.4):
    ser.reset_input_buffer()
    ser.write((text + "\n").encode())
    return drain(ser, wait)

def check(name, ok, detail=""):
    global passed, failed
    mark = "PASS" if ok else "FAIL"
    if ok: passed += 1
    else:  failed += 1
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail else ""))

def expect_line(name, lines, prefix):
    hit = next((l for l in lines if l.startswith(prefix)), None)
    check(name, hit is not None, hit or f"expected a line starting '{prefix}', got {lines}")
    return hit

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port"); ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for p in list_ports.comports(): print(p.device, "-", p.description)
        return

    port = a.port or find_port()
    if not port:
        sys.exit("No serial port found. Plug in the Arduino, or pass --port.")
    print(f"Opening {port} @ {BAUD} ...")
    ser = serial.Serial(port, BAUD, timeout=0.3)
    time.sleep(2.0)               # Arduino auto-resets on connect; wait for boot
    boot = drain(ser, 1.0)
    print(f"  boot banner: {boot}")

    print("\n-- Protocol handshake --")
    expect_line("T1 PING -> PONG", cmd(ser, "PING"), "PONG")

    print("\n-- Single-joint commands echo position --")
    expect_line("T2 J1:45 -> POS", cmd(ser, "J1:45", 1.5), "POS:45,")
    expect_line("T3 J2:120 -> POS", cmd(ser, "J2:120", 1.5), "POS:45,120,")
    expect_line("T4 J3:60 -> POS", cmd(ser, "J3:60", 1.5), "POS:45,120,60")

    print("\n-- Combined move + limit clamp --")
    expect_line("T5 MOVE:90,90,90 home", cmd(ser, "MOVE:90,90,90", 2.0), "POS:90,90,90")
    expect_line("T6 MOVE:999 clamps to 180", cmd(ser, "MOVE:999,90,90", 2.5), "POS:180,90,90")
    cmd(ser, "MOVE:90,90,90", 2.0)

    print("\n-- Electromagnet --")
    expect_line("T7 MAG:1 on", cmd(ser, "MAG:1"), "MAG:1")
    expect_line("T8 MAG:0 off", cmd(ser, "MAG:0"), "MAG:0")

    print("\n-- Bad input is rejected, not silently swallowed --")
    expect_line("T9 garbage -> ERR", cmd(ser, "WOBBLE"), "ERR:")

    print("\n-- Full swap sequence walks all 8 states in order --")
    ser.reset_input_buffer()
    ser.write(b"SEQ:START\n")
    seq, t0 = [], time.time()
    while time.time() - t0 < 40:
        raw = ser.readline().decode(errors="replace").strip()
        if raw:
            seq.append(raw)
            if raw == "DONE:CLEAR": break
    states = [l.split(":")[1] for l in seq if l.startswith("STATE:")]
    want = ["IDLE","AUTHENTICATE","GRIP_DEPLETED","DEPOSIT",
            "PICK_CHARGED","INSERT","CONFIRM","CLEAR"]
    check("T10 all 8 states, in order", states == want, f"got {states}")
    check("T11 sequence finished (DONE:CLEAR)", "DONE:CLEAR" in seq)
    check("T12 magnet asserted during grip", "MAG:1" in seq)
    check("T13 pack reported at grip", any(l.startswith("PACK:PK") for l in seq))
    dur = time.time() - t0
    check("T14 cycle under 90s target", dur < 90, f"{dur:.1f}s")

    print("\n-- E-STOP releases magnet mid-sequence --")
    ser.write(b"SEQ:START\n"); time.sleep(2.0)
    stop = cmd(ser, "ESTOP", 1.0)
    check("T15 ESTOP -> MAG:0 + ERR:ESTOP",
          any(l == "MAG:0" for l in stop) and any("ESTOP" in l for l in stop),
          str(stop))

    cmd(ser, "HOME", 2.0)
    ser.close()
    print(f"\n{'='*40}\n  {passed} passed, {failed} failed\n{'='*40}")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
