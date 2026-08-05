[README.md](https://github.com/user-attachments/files/30764936/README.md)
# Reswap — Ground Control System + Swap-Arm Firmware

Operator dashboard and hardware controller for an autonomous drone battery-swapping
station. A browser-based Ground Control System (GCS) drives a physical 3-servo swap
arm directly over USB, with no backend server in between.

The fleet and site map are simulated (you don't fly six real drones to test an
operations layer); the swap arm is real hardware driven over the serial link. When
a simulated drone docks at a station, the GCS selects which charged battery to
install and commands the arm to swap it for the drone's depleted pack.

## Repository layout

```
mission-control/
  reswap_mission_control.html   Single-file GCS. Open in Chrome/Edge. No build step.
firmware/
  reswap_arm_firmware/
    reswap_arm_firmware.ino      Arduino sketch: 3 servos + electromagnet, serial protocol.
tests/
  test_arm_link.py               Host-side protocol test harness (pyserial).
docs/
  PROTOCOL.md                    The serial protocol shared by the GCS and firmware.
```

## Architecture

```
  Browser (GCS)  ── Web Serial / USB ──▶  Arduino Uno  ──▶  3× MG996R servos + electromagnet
  simulated fleet + map                    reswap_arm_firmware.ino
  mission builder + library
  site setup (map points)
```

The GCS and firmware share one line-based serial protocol (see `docs/PROTOCOL.md`).
The GCS never talks to a backend for the arm — it opens the USB port directly via the
browser Web Serial API. A `localhost:8000` backend adapter seam exists in the code for
a future MAVSDK/FastAPI layer but is not required to run.

## Run it

### GCS (dashboard)
1. Open `mission-control/reswap_mission_control.html` in **desktop Chrome or Edge**
   (Web Serial is Chromium-only; it is not available in Firefox/Safari).
2. The map, fleet, and mission simulation run immediately — no hardware needed.

### Firmware (swap arm)
1. Open `firmware/reswap_arm_firmware/reswap_arm_firmware.ino` in the Arduino IDE.
2. Select the board (Arduino Uno) and port, then Upload. The `Servo` library is built in.
3. Wiring (default pin map, editable at the top of the sketch):
   - J1 base servo signal → D9
   - J2 shoulder servo signal → D10
   - J3 elbow servo signal → D11
   - Electromagnet (via a logic-level MOSFET, not direct) → D6
   - Optional grip switch (active-LOW) → D7
   - Power all three servos from a separate 5–6 V supply (>=5 A) with a common ground
     to the Arduino. Do not power servos from the Uno's 5V pin under load.

### Connect the GCS to the arm
1. Close the Arduino IDE Serial Monitor (it locks the port).
2. In the GCS, click the Arduino chip → open the Swap Arm Console → **Connect Arduino** →
   pick the port. A `PONG` in the serial monitor confirms the link.
3. Flip **Auto-swap arm when a drone docks** on. Docking drones now trigger the arm.
   Or use **Simulate a dock now** to fire one immediately for testing.

### Tests
```
pip install pyserial
python tests/test_arm_link.py          # auto-detects the port
python tests/test_arm_link.py --list   # list serial ports
```
Runs the full protocol contract (handshake through the 8-state swap sequence and E-STOP).

## Features

- Live site map with fleet, stations, waypoints, and routes.
- Mission builder + saved-mission library: create, edit, pin, and one-tap launch.
  Missions and pins persist in the browser.
- Site setup: place/name/delete delivery, inspection, and station points by clicking
  the map; the mission builder references these points.
- Swap Arm Console: connect over USB, jog each joint, toggle the magnet, run the swap
  sequence, quick-move presets, a scriptable motion editor, and a live serial monitor.
- Autonomous demo loop: drones periodically dock and the GCS drives the arm to swap.

## Status / known limitations

- **Fleet is simulated; the arm is real.** By design.
- **Arm poses are placeholder angles**, not yet calibrated to a physical arm. Motion runs
  in the correct sequence but is not tuned to grip a real pack. Run clear of obstacles.
- **The grip force sensor is stubbed** in firmware (always reports "gripped"). Wire a real
  switch before trusting grip confirmation.
- The GCS has been validated for structure and JS syntax; render it in a browser to confirm
  layout on your machine.

## Tech

Single-file HTML/CSS/JS (no framework, no build). Web Serial API. Arduino/C++ (Servo).
Python + pyserial for tests.
