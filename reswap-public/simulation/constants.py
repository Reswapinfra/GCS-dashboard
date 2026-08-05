"""
Reswap — Shared constants
Single source of truth. Updated from Sudheer's handoff doc (June 28, 2026).
Import this everywhere — never hardcode these values.
"""

# ── Timing (Sudheer handoff, locked) ─────────────────────────────────────────
SWAP_TIME_MIN         = 78 / 60        # 78s worst-case modeled (was 90s target)
SWAP_TIME_TARGET_MIN  = 90 / 60        # 90s hard ceiling
FLIGHT_TIME_MIN       = 25.0           # per full charge, industrial drone
RECHARGE_TIME_MIN     = 40.0           # without swap — the downtime Reswap kills
BELT_SPEED_MPS        = 0.05           # 50 mm/s vertical belt drive

# ── Station hardware (Sudheer handoff, locked) ────────────────────────────────
MODULES_PER_STATION   = 5              # default; range 2–8+
SOCKETS_PER_MODULE    = 12             # ring layout, inward facing
SOCKETS_PER_STATION   = MODULES_PER_STATION * SOCKETS_PER_MODULE  # = 60
STATION_DIAMETER_MM   = 640
STATION_HEIGHT_MM     = 1350
PACK_DIMS_MM          = (95, 82.5, 50) # Reswap custom format

# Arm is 2-DOF (rotate + extend), NOT 3-DOF RRR as previously assumed
ARM_DOF               = 2
ARM_REACH_MM          = 310            # max extend

# Drone docks from BELOW (bottom aperture), not top
DOCK_FROM             = "bottom"

# ── Business (Sudheer handoff, locked) ────────────────────────────────────────
SWAP_FEE_LOW          = 8.0
SWAP_FEE_HIGH         = 15.0
SWAP_FEE_DEFAULT      = 12.0           # midpoint (was $11.50)
SAAS_MONTHLY_LOW      = 500
SAAS_MONTHLY_HIGH     = 2000
SAAS_MONTHLY_DEFAULT  = 750

# ── Fleet / ops ───────────────────────────────────────────────────────────────
OPERATING_HOURS       = 10             # 10-hr industrial shift
FLIGHT_SPEED_MPS      = 15.0           # ~54 km/h

# ── Battery / energy ──────────────────────────────────────────────────────────
BATTERY_CAPACITY_WH   = 400
ENERGY_PER_SEC        = BATTERY_CAPACITY_WH / (FLIGHT_TIME_MIN * 60)

# ── Duty cycle math (from Sudheer's doc, for YC narrative) ────────────────────
# Without Reswap: 25 min fly + 40 min charge = 65 min cycle → 38.5% duty cycle
# With Reswap:    25 min fly + 1.3 min swap  = 26.3 min cycle → 95.0% duty cycle
DUTY_CYCLE_BASELINE   = FLIGHT_TIME_MIN / (FLIGHT_TIME_MIN + RECHARGE_TIME_MIN)
DUTY_CYCLE_RESWAP     = FLIGHT_TIME_MIN / (FLIGHT_TIME_MIN + SWAP_TIME_MIN)
THROUGHPUT_MULTIPLIER = DUTY_CYCLE_RESWAP / DUTY_CYCLE_BASELINE   # ~2.47×

# ── Station init state ────────────────────────────────────────────────────────
# Start shift with 50 charged, 10 depleted (realistic overnight pre-charge)
STATION_INIT_CHARGED  = 50
STATION_INIT_DEPLETED = 10
