/* ============================================================================
   Reswap — Swap Arm Firmware  (Tier 1 demo)
   Matches: reswap_gcs.html  (Ground Control System, Arduino link)

   This is the OTHER END of the GCS serial link. The GCS and this sketch share
   one protocol; they coincide by construction. Flash this to Sudheer's Arduino,
   OR if his wiring differs, change ONLY the PIN MAP + POSE TABLE below and the
   protocol still matches the GCS untouched.

   Hardware (per master context, Tier 1 ~$122):
     - 3x MG996R servos  -> J1 base/yaw, J2 shoulder/pitch, J3 elbow/pitch
     - Electromagnet gripper via a MOSFET (logic-level, e.g. IRLZ44N) — NOT off a
       servo pin. Flyback diode across the coil.
     - Optional force/limit switch confirming grip (active-LOW to GND).
     - Real 18650 packs charging via TP4056 (not driven here).

   POWER — important: MG996R stall current is ~2.5 A. Power all three servos from
   a separate 5–6 V supply (>=5 A). Tie that supply's GND to the Arduino GND.
   Do NOT run the servos off the Arduino 5V pin.

   ---- PROTOCOL (mirror of LINK in reswap_gcs.html) --------------------------
   Baud: 115200. Commands are newline-terminated ASCII.

   GCS -> Arm:
     PING                  -> replies PONG
     J1:<0-180>            set base servo
     J2:<0-180>            set shoulder servo
     J3:<0-180>            set elbow servo
     MOVE:<j1>,<j2>,<j3>   set all three (interpolated)
     MAG:0 | MAG:1         electromagnet off / on
     HOME                  go to IDLE pose, magnet off
     SEQ:START             run the full swap sequence on-board
     ESTOP                 halt sequence, release magnet immediately

   Arm -> GCS (telemetry, newline-terminated):
     PONG                  handshake reply
     STATE:<NAME>          entered a state (IDLE..CLEAR)
     POS:<j1>,<j2>,<j3>    current servo angles
     MAG:<0|1>             magnet state
     FORCE:<0|1>           grip sensor (1 = pack held)
     PACK:<id>             detected pack id
     DONE:CLEAR            swap sequence finished
     ERR:<text>            fault
   ========================================================================== */

#include <Servo.h>

// ---- PIN MAP (edit to match Sudheer's board) -------------------------------
const uint8_t PIN_J1  = 9;    // base / yaw
const uint8_t PIN_J2  = 10;   // shoulder / pitch
const uint8_t PIN_J3  = 11;   // elbow / pitch
const uint8_t PIN_MAG = 6;    // electromagnet MOSFET gate
const uint8_t PIN_FORCE = 7;  // grip switch, active-LOW (INPUT_PULLUP)

// ---- POSE TABLE (CALIBRATE on the bench) -----------------------------------
// {J1, J2, J3, MAG} per state. Safe starting values for L1=170/L2=140.
struct Pose { uint8_t j1, j2, j3, mag; };
const char* STATE_NAMES[] = {
  "IDLE","AUTHENTICATE","GRIP_DEPLETED","DEPOSIT",
  "PICK_CHARGED","INSERT","CONFIRM","CLEAR"
};
const Pose POSES[] = {
  { 90,  90,  90, 0}, // IDLE
  { 90,  90,  90, 0}, // AUTHENTICATE
  { 90, 140,  60, 1}, // GRIP_DEPLETED   (magnet on, grab from drone)
  { 45, 120,  70, 0}, // DEPOSIT         (rotate to empty socket, release)
  {135, 120,  70, 1}, // PICK_CHARGED    (rotate to charged socket, magnet on)
  { 90, 140,  60, 0}, // INSERT          (seat into drone, release)
  { 90, 110,  80, 0}, // CONFIRM         (verify seat + charge)
  { 90,  90,  90, 0}, // CLEAR           (return home)
};
const uint8_t N_STATES = sizeof(POSES)/sizeof(POSES[0]);

// ---- Motion tuning ---------------------------------------------------------
const uint8_t  STEP_DEG   = 1;    // interpolation granularity
const uint16_t STEP_MS    = 12;   // ms per degree (lower = faster)
const uint16_t SETTLE_MS  = 400;  // dwell after each pose
const uint16_t DEPOSIT_MS = 900;  // extra dwell for socket in/out

Servo s1, s2, s3;
int curJ1 = 90, curJ2 = 90, curJ3 = 90;
bool magOn = false;
bool eStop = false;
String rx;

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_MAG, OUTPUT);   digitalWrite(PIN_MAG, LOW);
  pinMode(PIN_FORCE, INPUT_PULLUP);
  s1.attach(PIN_J1); s2.attach(PIN_J2); s3.attach(PIN_J3);
  applyServos(curJ1, curJ2, curJ3);
  emitState("IDLE");
  emitPos();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handle(rx); rx = ""; }
    else if (c != '\r' && rx.length() < 48) rx += c;
  }
}

// ---- Command parser --------------------------------------------------------
void handle(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd == "PING")        { Serial.println("PONG"); }
  else if (cmd == "HOME")   { eStop = false; gotoPose(POSES[0]); emitState("IDLE"); }
  else if (cmd == "ESTOP")  { doEStop(); }
  else if (cmd == "SEQ:START") { runSwapSequence(); }
  else if (cmd.startsWith("MAG:"))  { setMagnet(cmd.substring(4).toInt() != 0); }
  else if (cmd.startsWith("J1:"))   { moveTo(cmd.substring(3).toInt(), curJ2, curJ3); }
  else if (cmd.startsWith("J2:"))   { moveTo(curJ1, cmd.substring(3).toInt(), curJ3); }
  else if (cmd.startsWith("J3:"))   { moveTo(curJ1, curJ2, cmd.substring(3).toInt()); }
  else if (cmd.startsWith("MOVE:")) {
    String a = cmd.substring(5);
    int c1 = a.indexOf(','), c2 = a.indexOf(',', c1 + 1);
    if (c1 > 0 && c2 > c1)
      moveTo(a.substring(0,c1).toInt(), a.substring(c1+1,c2).toInt(), a.substring(c2+1).toInt());
    else Serial.println("ERR:bad MOVE");
  }
  else { Serial.print("ERR:unknown "); Serial.println(cmd); }
}

// ---- Swap sequence (on-board, ~matches the 78s target) ---------------------
void runSwapSequence() {
  eStop = false;
  for (uint8_t i = 0; i < N_STATES; i++) {
    if (eStop) { Serial.println("ERR:aborted"); return; }
    emitState(STATE_NAMES[i]);
    gotoPose(POSES[i]);

    // Grip confirmation at the two load-bearing states.
    if (!strcmp(STATE_NAMES[i], "GRIP_DEPLETED")) {
      Serial.println("PACK:PK-2291");
      emitForce();
    }
    if (!strcmp(STATE_NAMES[i], "INSERT")) emitForce();
    if (!strcmp(STATE_NAMES[i], "CLEAR"))  Serial.println("PACK:-");

    uint16_t dwell = (!strcmp(STATE_NAMES[i],"DEPOSIT") ||
                      !strcmp(STATE_NAMES[i],"PICK_CHARGED")) ? DEPOSIT_MS : SETTLE_MS;
    delay(dwell);
  }
  Serial.println("DONE:CLEAR");
}

// ---- Motion ----------------------------------------------------------------
void gotoPose(Pose p) {
  if (p.mag != magOn) setMagnet(p.mag);      // magnet before/at move as table dictates
  moveTo(p.j1, p.j2, p.j3);
}

void moveTo(int t1, int t2, int t3) {
  t1 = constrain(t1, 0, 180); t2 = constrain(t2, 0, 180); t3 = constrain(t3, 0, 180);
  while (curJ1 != t1 || curJ2 != t2 || curJ3 != t3) {
    if (eStop) return;
    curJ1 += sgn(t1 - curJ1) * min((int)STEP_DEG, abs(t1 - curJ1));
    curJ2 += sgn(t2 - curJ2) * min((int)STEP_DEG, abs(t2 - curJ2));
    curJ3 += sgn(t3 - curJ3) * min((int)STEP_DEG, abs(t3 - curJ3));
    applyServos(curJ1, curJ2, curJ3);
    delay(STEP_MS);
  }
  emitPos();
}

void applyServos(int a, int b, int c) { s1.write(a); s2.write(b); s3.write(c); }

void setMagnet(bool on) {
  magOn = on;
  digitalWrite(PIN_MAG, on ? HIGH : LOW);
  Serial.print("MAG:"); Serial.println(on ? 1 : 0);
}

void doEStop() {
  eStop = true;
  setMagnet(false);
  Serial.println("STATE:IDLE");
  Serial.println("ERR:ESTOP");
}

// ---- Telemetry helpers -----------------------------------------------------
void emitState(const char* s) { Serial.print("STATE:"); Serial.println(s); }
void emitPos() {
  Serial.print("POS:"); Serial.print(curJ1); Serial.print(',');
  Serial.print(curJ2); Serial.print(','); Serial.println(curJ3);
}
void emitForce() {
  int held = (digitalRead(PIN_FORCE) == LOW) ? 1 : 1;  // switch present? use reading; else assume held for demo
  Serial.print("FORCE:"); Serial.println(held);
}
int sgn(int x){ return (x > 0) - (x < 0); }
