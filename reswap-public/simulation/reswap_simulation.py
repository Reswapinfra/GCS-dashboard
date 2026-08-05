"""
Reswap — Fleet Simulation
Updated: Sudheer handoff June 28, 2026.

Changes from v1:
  - SOCKETS_PER_STATION: 10 → 60 (5 modules × 12 sockets)
  - SWAP_TIME_MIN: 1.5 → 1.3 (78s modeled worst case)
  - SWAP_FEE_DEFAULT: $11.50 → $12.00
  - All constants imported from constants.py (single source of truth)
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from dataclasses import dataclass
from typing import List, Optional
import math

from constants import (
    SWAP_TIME_MIN, FLIGHT_TIME_MIN, RECHARGE_TIME_MIN,
    SOCKETS_PER_STATION, STATION_INIT_CHARGED, STATION_INIT_DEPLETED,
    OPERATING_HOURS, SWAP_FEE_LOW, SWAP_FEE_HIGH, SWAP_FEE_DEFAULT,
    SAAS_MONTHLY_DEFAULT, DUTY_CYCLE_BASELINE, DUTY_CYCLE_RESWAP,
)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class DroneState:
    drone_id: int
    status: str = "charging"     # charging | flying | swapping | waiting
    battery_pct: float = 100.0
    missions_completed: int = 0
    total_flight_min: float = 0.0
    total_swap_count: int = 0
    time_flying: float = 0.0
    time_charging: float = 0.0
    time_swapping: float = 0.0
    time_waiting: float = 0.0


@dataclass
class StationState:
    station_id: int
    sockets: int = SOCKETS_PER_STATION          # 60
    charged_packs: float = STATION_INIT_CHARGED  # 50
    depleted_packs: float = STATION_INIT_DEPLETED # 10
    total_swaps: int = 0
    busy_until: float = 0.0


@dataclass
class SimResult:
    mode: str
    fleet_size: int
    missions_per_day: int
    fleet_utilization_pct: float
    avg_drone_daily_flight_min: float
    total_swaps: int
    revenue_low: float
    revenue_high: float
    revenue_default: float
    minutes_simulated: float
    timeline: pd.DataFrame


# ─── Core simulation ──────────────────────────────────────────────────────────

def simulate(
    fleet_size: int = 5,
    num_stations: int = 2,
    mission_flight_min: float = FLIGHT_TIME_MIN,
    use_swap: bool = True,
    operating_hours: float = OPERATING_HOURS,
    dt: float = 0.5,
    seed: int = 42,
) -> SimResult:
    rng = np.random.default_rng(seed)
    total_minutes = operating_hours * 60
    mode = "Reswap" if use_swap else "Baseline"

    drones: List[DroneState] = []
    for i in range(fleet_size):
        d = DroneState(drone_id=i)
        d.battery_pct = rng.uniform(60, 100)
        d.status = "charging"
        d._charge_done_at = (1 - d.battery_pct / 100) * RECHARGE_TIME_MIN
        drones.append(d)

    stations: List[StationState] = [StationState(s) for s in range(num_stations)]
    timers = {d.drone_id: {"done_at": d._charge_done_at} for d in drones}
    timeline_rows = []

    t = 0.0
    while t <= total_minutes:
        for d in drones:
            done_at = timers[d.drone_id]["done_at"]

            if d.status == "charging":
                if t >= done_at:
                    d.battery_pct = 100.0
                    d.status = "flying"
                    timers[d.drone_id]["done_at"] = t + mission_flight_min
                else:
                    d.time_charging += dt

            elif d.status == "flying":
                d.time_flying += dt
                if t >= done_at:
                    d.missions_completed += 1
                    d.battery_pct = 0.0
                    d.total_flight_min += mission_flight_min
                    if use_swap:
                        station = _get_available_station(stations, t)
                        if station is not None:
                            d.status = "swapping"
                            station.busy_until = t + SWAP_TIME_MIN
                            station.total_swaps += 1
                            station.charged_packs -= 1
                            station.depleted_packs += 1
                            d.total_swap_count += 1
                            timers[d.drone_id]["done_at"] = t + SWAP_TIME_MIN
                        else:
                            d.status = "waiting"
                            timers[d.drone_id]["done_at"] = t + dt
                    else:
                        d.status = "charging"
                        timers[d.drone_id]["done_at"] = t + RECHARGE_TIME_MIN

            elif d.status == "swapping":
                d.time_swapping += dt
                if t >= done_at:
                    d.battery_pct = 100.0
                    d.status = "flying"
                    timers[d.drone_id]["done_at"] = t + mission_flight_min

            elif d.status == "waiting":
                d.time_waiting += dt
                station = _get_available_station(stations, t)
                if station is not None:
                    d.status = "swapping"
                    station.busy_until = t + SWAP_TIME_MIN
                    station.total_swaps += 1
                    station.charged_packs -= 1
                    station.depleted_packs += 1
                    d.total_swap_count += 1
                    timers[d.drone_id]["done_at"] = t + SWAP_TIME_MIN

        for s in stations:
            rate = dt / RECHARGE_TIME_MIN
            newly = min(s.depleted_packs * rate, s.depleted_packs)
            s.charged_packs = min(s.charged_packs + newly, s.sockets)
            s.depleted_packs = max(s.depleted_packs - newly, 0)

        if math.isclose(t % 30, 0, abs_tol=dt / 2):
            flying   = sum(1 for d in drones if d.status == "flying")
            swapping = sum(1 for d in drones if d.status == "swapping")
            charging = sum(1 for d in drones if d.status == "charging")
            waiting  = sum(1 for d in drones if d.status == "waiting")
            missions = sum(d.missions_completed for d in drones)
            timeline_rows.append({
                "time_min": t, "flying": flying, "swapping": swapping,
                "charging": charging, "waiting": waiting, "missions_total": missions,
            })

        t = round(t + dt, 6)

    total_missions  = sum(d.missions_completed for d in drones)
    total_flight    = sum(d.time_flying for d in drones)
    utilization     = (total_flight / (fleet_size * total_minutes)) * 100
    total_swaps     = sum(s.total_swaps for s in stations)

    return SimResult(
        mode=mode,
        fleet_size=fleet_size,
        missions_per_day=total_missions,
        fleet_utilization_pct=round(utilization, 1),
        avg_drone_daily_flight_min=round(total_flight / fleet_size, 1),
        total_swaps=total_swaps,
        revenue_low=total_swaps * SWAP_FEE_LOW,
        revenue_high=total_swaps * SWAP_FEE_HIGH,
        revenue_default=total_swaps * SWAP_FEE_DEFAULT,
        minutes_simulated=total_minutes,
        timeline=pd.DataFrame(timeline_rows),
    )


def _get_available_station(stations, t):
    for s in stations:
        if s.busy_until <= t and s.charged_packs >= 1:
            return s
    return None


# ─── Analysis helpers ─────────────────────────────────────────────────────────

def run_fleet_sweep(fleet_sizes=(2, 5, 10, 20), num_stations=2):
    rows = []
    for n in fleet_sizes:
        for use_swap in [False, True]:
            r = simulate(fleet_size=n, num_stations=num_stations, use_swap=use_swap)
            rows.append({
                "fleet_size": n, "mode": r.mode,
                "missions_per_day": r.missions_per_day,
                "utilization_pct": r.fleet_utilization_pct,
                "revenue_default": r.revenue_default,
                "total_swaps": r.total_swaps,
            })
    return pd.DataFrame(rows)


def revenue_sensitivity(fleet_size=10, num_stations=2):
    r = simulate(fleet_size=fleet_size, num_stations=num_stations, use_swap=True)
    swaps_per_station = r.total_swaps / max(num_stations, 1)
    return pd.DataFrame([{
        "swap_fee": fee,
        "swaps_per_station": swaps_per_station,
        "revenue_per_station_day": swaps_per_station * fee,
    } for fee in [5, 8, 10, 12, 15, 20]])


def breakeven_analysis(
    station_hardware_cost=5000,
    monthly_saas=SAAS_MONTHLY_DEFAULT,
    fleet_size=10,
    num_stations=2,
    fee=SWAP_FEE_DEFAULT,
):
    r = simulate(fleet_size=fleet_size, num_stations=num_stations, use_swap=True)
    daily = (r.total_swaps / num_stations) * fee + monthly_saas / 30
    days  = station_hardware_cost / daily if daily > 0 else float('inf')
    return {
        "daily_revenue_per_station": round(daily, 2),
        "days_to_breakeven": round(days, 1),
        "months_to_breakeven": round(days / 30, 1),
        "annual_revenue_per_station": round(daily * 365, 0),
    }


# ─── Plot ─────────────────────────────────────────────────────────────────────

def plot_results(output_path="/mnt/user-data/outputs/reswap_week1_sim.png"):
    fleet_sizes = [2, 5, 10, 20]
    sweep = run_fleet_sweep(fleet_sizes=fleet_sizes, num_stations=2)
    baseline = sweep[sweep["mode"] == "Baseline"].reset_index(drop=True)
    reswap   = sweep[sweep["mode"] == "Reswap"].reset_index(drop=True)
    r_base   = simulate(fleet_size=10, use_swap=False)
    r_swap   = simulate(fleet_size=10, use_swap=True)

    C_BASE="#4A6FA5"; C_SWAP="#00D48A"; C_GRID="#21262D"
    C_TEXT="#8B949E"; C_WHITE="#E6EDF3"; C_GOLD="#F0A500"

    fig = plt.figure(figsize=(16, 10), facecolor="#0D1117")
    fig.suptitle("RESWAP — Fleet Simulation  |  Updated: Sudheer Handoff",
                 fontsize=17, fontweight="bold", color=C_WHITE, y=0.97)
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.38,
                           left=0.07, right=0.97, top=0.90, bottom=0.09)

    def style_ax(ax, title):
        ax.set_facecolor("#161B22")
        ax.tick_params(colors=C_TEXT, labelsize=9)
        ax.xaxis.label.set_color(C_TEXT); ax.yaxis.label.set_color(C_TEXT)
        ax.set_title(title, fontsize=11, fontweight="bold", color=C_WHITE, pad=8)
        for sp in ax.spines.values(): sp.set_edgecolor(C_GRID)
        ax.grid(axis='y', color=C_GRID, linewidth=0.8)

    x = np.arange(len(fleet_sizes)); w = 0.35

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.bar(x-w/2, baseline.missions_per_day.values, w, color=C_BASE, label="Baseline")
    ax1.bar(x+w/2, reswap.missions_per_day.values,   w, color=C_SWAP, label="Reswap")
    ax1.set_xticks(x); ax1.set_xticklabels([f"{n} drones" for n in fleet_sizes])
    ax1.set_ylabel("Missions / day")
    ax1.legend(fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")
    for i,(b,r_) in enumerate(zip(baseline.missions_per_day.values, reswap.missions_per_day.values)):
        mult = r_/b if b>0 else 0
        ax1.text(x[i]+w/2, r_+1, f"{mult:.1f}×", ha='center', fontsize=8, color=C_GOLD, fontweight='bold')
    style_ax(ax1, "Missions Completed per Day")

    ax2 = fig.add_subplot(gs[0, 1])
    ax2.bar(x-w/2, baseline.utilization_pct.values, w, color=C_BASE, label="Baseline")
    ax2.bar(x+w/2, reswap.utilization_pct.values,   w, color=C_SWAP, label="Reswap")
    ax2.set_xticks(x); ax2.set_xticklabels([f"{n} drones" for n in fleet_sizes])
    ax2.set_ylabel("Utilization (%)"); ax2.set_ylim(0, 105)
    duty_base_pct = round(DUTY_CYCLE_BASELINE * 100, 1)
    duty_swap_pct = round(DUTY_CYCLE_RESWAP * 100, 1)
    ax2.axhline(duty_base_pct, color=C_BASE, lw=0.8, ls='--', alpha=0.5)
    ax2.axhline(duty_swap_pct, color=C_SWAP, lw=0.8, ls='--', alpha=0.5)
    ax2.legend(fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")
    style_ax(ax2, "Fleet Utilization %")

    ax3 = fig.add_subplot(gs[0, 2])
    rev = revenue_sensitivity(fleet_size=10, num_stations=2)
    bars = ax3.bar(rev.swap_fee.astype(str), rev.revenue_per_station_day,
                   color=C_SWAP, alpha=0.85)
    # Highlight $12 default
    for bar, fee in zip(bars, rev.swap_fee):
        if fee == 12:
            bar.set_color(C_GOLD)
    ax3.set_xlabel("Swap fee ($)"); ax3.set_ylabel("Revenue / station / day ($)")
    ax3.legend(handles=[
        plt.Rectangle((0,0),1,1,color=C_GOLD, label="$12 default (Sudheer)"),
        plt.Rectangle((0,0),1,1,color=C_SWAP, label="Other fees"),
    ], fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")
    style_ax(ax3, "Revenue per Station per Day")

    ax4 = fig.add_subplot(gs[1, 0:2])
    tl_b = r_base.timeline; tl_s = r_swap.timeline
    ax4.fill_between(tl_b.time_min/60, tl_b.flying, alpha=0.2, color=C_BASE)
    ax4.plot(tl_b.time_min/60, tl_b.flying, color=C_BASE, lw=2, label="Baseline — flying")
    ax4.fill_between(tl_s.time_min/60, tl_s.flying, alpha=0.2, color=C_SWAP)
    ax4.plot(tl_s.time_min/60, tl_s.flying, color=C_SWAP, lw=2, label="Reswap — flying")
    ax4.set_xlabel("Hours into shift"); ax4.set_ylabel("Drones in air")
    ax4.legend(fontsize=9, labelcolor=C_TEXT, facecolor="#21262D"); ax4.set_xlim(0, 10)
    style_ax(ax4, "Active Drones in Air — 10-Drone Fleet, 10-Hour Shift")

    ax5 = fig.add_subplot(gs[1, 2])
    ax5.set_facecolor("#161B22")
    for sp in ax5.spines.values(): sp.set_edgecolor(C_GRID)
    ax5.set_xticks([]); ax5.set_yticks([])
    be = breakeven_analysis()
    lines = [
        ("BREAK-EVEN (UPDATED)", C_WHITE, 12, "bold"),
        (f"60 packs/station (5×12)", C_TEXT, 9, "normal"),
        (f"Swap fee: $12.00 (locked)", C_TEXT, 9, "normal"),
        (f"SaaS: ${SAAS_MONTHLY_DEFAULT}/mo", C_TEXT, 9, "normal"),
        ("", C_TEXT, 7, "normal"),
        ("Daily rev / station", C_TEXT, 9, "normal"),
        (f"  ${be['daily_revenue_per_station']:.0f}", C_SWAP, 15, "bold"),
        ("", C_TEXT, 7, "normal"),
        ("Break-even", C_TEXT, 9, "normal"),
        (f"  {be['months_to_breakeven']} months", C_GOLD, 15, "bold"),
        ("", C_TEXT, 7, "normal"),
        ("Annual rev / station", C_TEXT, 9, "normal"),
        (f"  ${be['annual_revenue_per_station']:,.0f}", C_SWAP, 13, "bold"),
    ]
    y_pos = 0.95
    for text, color, size, weight in lines:
        ax5.text(0.07, y_pos, text, transform=ax5.transAxes,
                 color=color, fontsize=size, fontweight=weight, va='top')
        y_pos -= 0.07 if size >= 12 else 0.073
    ax5.set_title("Unit Economics", fontsize=11, fontweight="bold", color=C_WHITE, pad=8)

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor="#0D1117")
    print(f"Saved → {output_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("RESWAP — Fleet Simulation (updated: Sudheer handoff)")
    print(f"Station sockets: {SOCKETS_PER_STATION} | Swap time: {SWAP_TIME_MIN*60:.0f}s | Fee: ${SWAP_FEE_DEFAULT}")
    print("=" * 60)

    for use_swap in [False, True]:
        r = simulate(fleet_size=10, num_stations=2, use_swap=use_swap)
        print(f"\nMode: {r.mode}")
        print(f"  Missions/day:        {r.missions_per_day}")
        print(f"  Fleet utilization:   {r.fleet_utilization_pct}%")
        print(f"  Avg flight/drone:    {r.avg_drone_daily_flight_min} min")
        if use_swap:
            print(f"  Total swaps:         {r.total_swaps}")
            print(f"  Revenue (@$12):      ${r.revenue_default:,.0f}")

    print("\nBreak-even:")
    be = breakeven_analysis()
    for k, v in be.items():
        print(f"  {k}: {v}")

    print("\nGenerating chart...")
    plot_results()
    print("Done.")
