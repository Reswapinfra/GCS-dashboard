# Reswap Arm Serial Protocol

Line-based ASCII over USB serial at **115200 baud**. Every message is one line
terminated by `\n`. The GCS (`reswap_mission_control.html`) and the firmware
(`reswap_arm_firmware.ino`) both implement this contract; the test harness
(`test_arm_link.py`) verifies it.

## GCS → Arm (commands)

| Command            | Meaning                                              |
|--------------------|------------------------------------------------------|
| `PING`             | Handshake; arm replies `PONG`                        |
| `J1:<0-180>`       | Set base/yaw servo angle                             |
| `J2:<0-180>`       | Set shoulder servo angle                             |
| `J3:<0-180>`       | Set elbow servo angle                                |
| `MOVE:<j1>,<j2>,<j3>` | Set all three servos (interpolated)               |
| `MAG:0` / `MAG:1`  | Electromagnet off / on                               |
| `HOME`             | Go to the IDLE pose, magnet off                      |
| `SEQ:START`        | Run the full swap sequence on-board                  |
| `ESTOP`            | Halt sequence immediately, release magnet            |

Angles are clamped to 0–180 by the firmware.

## Arm → GCS (telemetry)

| Message              | Meaning                                            |
|----------------------|----------------------------------------------------|
| `PONG`               | Handshake reply                                    |
| `STATE:<NAME>`       | Entered a swap state (see below)                   |
| `POS:<j1>,<j2>,<j3>` | Current servo angles (sent after each move)        |
| `MAG:<0\|1>`         | Magnet state                                       |
| `FORCE:<0\|1>`       | Grip sensor (1 = pack held) — currently stubbed    |
| `PACK:<id>`          | Detected/held pack id                              |
| `DONE:CLEAR`         | Swap sequence finished                             |
| `ERR:<text>`         | Fault / unknown command                            |

## Swap state machine

`IDLE → AUTHENTICATE → GRIP_DEPLETED → DEPOSIT → PICK_CHARGED → INSERT → CONFIRM → CLEAR`

The firmware runs this sequence on-board when it receives `SEQ:START`, emitting a
`STATE:` line as it enters each state and `DONE:CLEAR` at the end. The GCS mirrors
the sequence in its console and activity log.

## Flow control

Motion commands block on the arm until the move completes, then echo `POS:`. When the
GCS plays a multi-step motion it waits for each `POS:`/`MAG:` echo (with a timeout)
before sending the next command, so the Arduino's 64-byte serial buffer never overflows.

## GCS-orchestrated swap (battery selection)

For the autonomous demo, the GCS composes the swap itself rather than using the
on-board `SEQ:START`: it selects an empty socket for the drone's discharged pack and a
charged socket to install, maps each socket to a J1 base angle, and streams the
`MOVE:`/`MAG:` steps. This is where battery selection logic lives on the GCS side.
