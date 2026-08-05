"""
Reswap — Route Optimizer
Updated: Sudheer handoff June 28, 2026.

Changes from v1:
  - SOCKETS_PER_STATION: 10 → 60
  - SWAP_TIME_MIN: 1.5 → 1.3 (78s)
  - SWAP_FEE_DEFAULT: $11.50 → $12.00
  - All constants from constants.py
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from dataclasses import dataclass
from typing import List, Tuple, Optional
from itertools import combinations
import math

from constants import (
    SWAP_TIME_MIN, FLIGHT_TIME_MIN, RECHARGE_TIME_MIN,
    SOCKETS_PER_STATION, STATION_INIT_CHARGED, STATION_INIT_DEPLETED,
    OPERATING_HOURS, SWAP_FEE_LOW, SWAP_FEE_HIGH, SWAP_FEE_DEFAULT,
    FLIGHT_SPEED_MPS, BATTERY_CAPACITY_WH, ENERGY_PER_SEC,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Waypoint:
    wp_id: str
    x: float
    y: float
    kind: str           # 'inspection' | 'delivery'
    priority: int = 1


@dataclass
class Station:
    station_id: str
    x: float
    y: float
    sockets: int = SOCKETS_PER_STATION           # 60
    charged_packs: float = STATION_INIT_CHARGED   # 50
    depleted_packs: float = STATION_INIT_DEPLETED # 10
    busy_until: float = 0.0
    total_swaps: int = 0


@dataclass
class Drone:
    drone_id: int
    x: float
    y: float
    status: str = "idle"
    battery_wh: float = BATTERY_CAPACITY_WH
    missions_completed: int = 0
    total_swaps: int = 0
    time_flying: float = 0.0
    time_grounded: float = 0.0
    current_target: Optional[Waypoint] = None
    current_station: Optional[Station] = None
    arrive_at: float = 0.0


@dataclass
class RouteResult:
    mode: str
    station_positions: List[Tuple[float, float]]
    missions_per_day: int
    fleet_utilization_pct: float
    total_swaps: int
    avg_transit_to_station_min: float
    revenue_low: float
    revenue_high: float
    revenue_default: float
    mission_log: pd.DataFrame
    drone_log: pd.DataFrame


# ── Helpers ───────────────────────────────────────────────────────────────────

def dist(ax, ay, bx, by) -> float:
    return math.sqrt((ax-bx)**2 + (ay-by)**2)

def flight_time_min(distance_m: float) -> float:
    return (distance_m / FLIGHT_SPEED_MPS) / 60.0

def nearest_station(drone: Drone, stations: List[Station], t: float) -> Station:
    with_packs = [s for s in stations if s.charged_packs >= 1]
    pool = with_packs if with_packs else stations
    return min(pool, key=lambda s: dist(drone.x, drone.y, s.x, s.y))


# ── Site generator ────────────────────────────────────────────────────────────

def generate_site(
    seed: int = 42,
    site_radius_m: float = 2000,
    n_inspection: int = 8,
    n_delivery: int = 4,
) -> Tuple[List[Waypoint], np.ndarray]:
    rng = np.random.default_rng(seed)
    waypoints = []
    for i in range(n_inspection):
        angle = rng.uniform(0, 2*math.pi)
        r = rng.uniform(site_radius_m*0.4, site_radius_m*0.9)
        waypoints.append(Waypoint(f"INS-{i+1:02d}", r*math.cos(angle), r*math.sin(angle),
                                  'inspection', int(rng.integers(1,3))))
    for i in range(n_delivery):
        angle = rng.uniform(0, 2*math.pi)
        r = rng.uniform(site_radius_m*0.5, site_radius_m)
        waypoints.append(Waypoint(f"DEL-{i+1:02d}", r*math.cos(angle), r*math.sin(angle),
                                  'delivery', 3))
    return waypoints, np.array([0.0, 0.0])


# ── Core route simulation ─────────────────────────────────────────────────────

def simulate_routes(
    fleet_size: int = 5,
    station_positions: List[Tuple[float, float]] = None,
    use_swap: bool = True,
    waypoints: List[Waypoint] = None,
    home_base: np.ndarray = None,
    operating_hours: float = OPERATING_HOURS,
    dt: float = 0.25,
    seed: int = 42,
) -> RouteResult:
    rng = np.random.default_rng(seed)
    if waypoints is None or home_base is None:
        waypoints, home_base = generate_site(seed=seed)
    if station_positions is None:
        station_positions = [(-600, 0), (600, 0)]

    stations = [Station(f"STN-{i+1:02d}", sx, sy)
                for i, (sx, sy) in enumerate(station_positions)]

    drones = [Drone(
        drone_id=i,
        x=home_base[0]+rng.uniform(-50,50),
        y=home_base[1]+rng.uniform(-50,50),
        battery_wh=rng.uniform(BATTERY_CAPACITY_WH*0.7, BATTERY_CAPACITY_WH),
    ) for i in range(fleet_size)]

    wp_queue = sorted(waypoints * 50, key=lambda w: (-w.priority, rng.random()))
    wp_idx = 0
    total_minutes = operating_hours * 60
    mission_log_rows = []
    transit_to_station_times = []

    t = 0.0
    while t <= total_minutes:
        # Recharge packs
        for s in stations:
            rate = dt / RECHARGE_TIME_MIN
            newly = min(s.depleted_packs * rate, s.depleted_packs)
            s.charged_packs = min(s.charged_packs + newly, s.sockets)
            s.depleted_packs = max(s.depleted_packs - newly, 0)

        for drone in drones:
            if drone.status == "idle":
                if wp_idx < len(wp_queue):
                    wp = wp_queue[wp_idx]; wp_idx += 1
                    drone.current_target = wp
                    d_m = dist(drone.x, drone.y, wp.x, wp.y)
                    nearest = min(stations, key=lambda s: dist(wp.x, wp.y, s.x, s.y))
                    d_to_stn = dist(wp.x, wp.y, nearest.x, nearest.y)
                    energy_needed = ((d_m + d_to_stn) / FLIGHT_SPEED_MPS) * ENERGY_PER_SEC
                    if drone.battery_wh < energy_needed * 0.9:
                        drone.status = "transit_to_station"
                        stn = nearest_station(drone, stations, t)
                        drone.current_station = stn
                        d_stn = dist(drone.x, drone.y, stn.x, stn.y)
                        drone.arrive_at = t + flight_time_min(d_stn)
                        drone.time_flying += flight_time_min(d_stn)
                        wp_idx -= 1
                    else:
                        ft = flight_time_min(d_m)
                        drone.status = "transit_to_wp"
                        drone.arrive_at = t + ft
                        drone.time_flying += ft
                        drone.battery_wh -= (d_m / FLIGHT_SPEED_MPS) * ENERGY_PER_SEC

            elif drone.status == "transit_to_wp":
                if t >= drone.arrive_at:
                    wp = drone.current_target
                    drone.x = wp.x; drone.y = wp.y
                    drone.missions_completed += 1
                    mission_log_rows.append({
                        "time_min": round(t,1), "drone_id": drone.drone_id,
                        "waypoint": wp.wp_id, "kind": wp.kind,
                    })
                    if use_swap:
                        stn = nearest_station(drone, stations, t)
                        drone.current_station = stn
                        d_stn = dist(drone.x, drone.y, stn.x, stn.y)
                        ft_stn = flight_time_min(d_stn)
                        transit_to_station_times.append(ft_stn)
                        drone.battery_wh -= (d_stn / FLIGHT_SPEED_MPS) * ENERGY_PER_SEC
                        drone.battery_wh = max(drone.battery_wh, 0)
                        drone.time_flying += ft_stn
                        drone.arrive_at = t + ft_stn
                        drone.status = "transit_to_station"
                    else:
                        d_home = dist(drone.x, drone.y, *home_base)
                        drone.battery_wh -= (d_home / FLIGHT_SPEED_MPS) * ENERGY_PER_SEC
                        drone.battery_wh = max(drone.battery_wh, 0)
                        drone.time_flying += flight_time_min(d_home)
                        drone.arrive_at = t + flight_time_min(d_home) + RECHARGE_TIME_MIN
                        drone.x = home_base[0]; drone.y = home_base[1]
                        drone.status = "charging"
                        drone.time_grounded += RECHARGE_TIME_MIN

            elif drone.status == "transit_to_station":
                if t >= drone.arrive_at:
                    stn = drone.current_station
                    drone.x = stn.x; drone.y = stn.y
                    if stn.charged_packs >= 1 and stn.busy_until <= t:
                        stn.busy_until = t + SWAP_TIME_MIN
                        stn.charged_packs -= 1
                        stn.depleted_packs += 1
                        stn.total_swaps += 1
                        drone.total_swaps += 1
                        drone.battery_wh = BATTERY_CAPACITY_WH
                        drone.arrive_at = t + SWAP_TIME_MIN
                        drone.status = "swapping"
                        drone.time_grounded += SWAP_TIME_MIN
                    else:
                        drone.status = "waiting"
                        drone.time_grounded += dt

            elif drone.status == "swapping":
                if t >= drone.arrive_at:
                    drone.status = "idle"

            elif drone.status == "charging":
                if t >= drone.arrive_at:
                    drone.battery_wh = BATTERY_CAPACITY_WH
                    drone.status = "idle"

            elif drone.status == "waiting":
                drone.time_grounded += dt
                stn = drone.current_station
                if stn.charged_packs >= 1 and stn.busy_until <= t:
                    stn.busy_until = t + SWAP_TIME_MIN
                    stn.charged_packs -= 1; stn.depleted_packs += 1
                    stn.total_swaps += 1; drone.total_swaps += 1
                    drone.battery_wh = BATTERY_CAPACITY_WH
                    drone.arrive_at = t + SWAP_TIME_MIN
                    drone.status = "swapping"

        t = round(t + dt, 6)

    total_missions  = sum(d.missions_completed for d in drones)
    total_flight    = sum(d.time_flying for d in drones)
    utilization     = (total_flight / (fleet_size * total_minutes)) * 100
    total_swaps     = sum(s.total_swaps for s in stations)
    avg_transit_stn = float(np.mean(transit_to_station_times)) if transit_to_station_times else 0.0

    drone_log = pd.DataFrame([{
        "drone_id": d.drone_id,
        "missions": d.missions_completed,
        "swaps": d.total_swaps,
        "time_flying_min": round(d.time_flying, 1),
        "time_grounded_min": round(d.time_grounded, 1),
    } for d in drones])

    return RouteResult(
        mode="Reswap" if use_swap else "Baseline",
        station_positions=station_positions,
        missions_per_day=total_missions,
        fleet_utilization_pct=round(utilization, 1),
        total_swaps=total_swaps,
        avg_transit_to_station_min=round(avg_transit_stn, 2),
        revenue_low=total_swaps * SWAP_FEE_LOW,
        revenue_high=total_swaps * SWAP_FEE_HIGH,
        revenue_default=total_swaps * SWAP_FEE_DEFAULT,
        mission_log=pd.DataFrame(mission_log_rows),
        drone_log=drone_log,
    )


# ── Station placement optimizer ───────────────────────────────────────────────

def optimize_station_placement(
    fleet_size=5, n_stations=2,
    waypoints=None, home_base=None,
    site_radius_m=2000, n_candidates=12, seed=42,
) -> Tuple[List[Tuple[float,float]], pd.DataFrame]:
    rng = np.random.default_rng(seed+1)
    if waypoints is None or home_base is None:
        waypoints, home_base = generate_site(seed=seed)

    candidates = []
    for r_frac in [0.45, 0.70]:
        for angle_deg in range(0, 360, 360//(n_candidates//2)):
            angle = math.radians(angle_deg)
            r = site_radius_m * r_frac
            candidates.append((r*math.cos(angle), r*math.sin(angle)))
    candidates += [(0,0),(300,300),(-300,-300),(300,-300)]
    candidates = list(set(candidates))[:n_candidates]

    rows = []
    best_score = -1; best_combo = None

    for combo in combinations(range(len(candidates)), n_stations):
        positions = [candidates[i] for i in combo]
        r = simulate_routes(fleet_size=fleet_size, station_positions=positions,
                            use_swap=True, waypoints=waypoints, home_base=home_base, dt=0.5)
        rows.append({
            "positions": str(positions),
            "missions_per_day": r.missions_per_day,
            "utilization_pct": r.fleet_utilization_pct,
            "total_swaps": r.total_swaps,
            "avg_transit_to_stn_min": r.avg_transit_to_station_min,
        })
        if r.missions_per_day > best_score:
            best_score = r.missions_per_day
            best_combo = positions

    scores_df = pd.DataFrame(rows).sort_values("missions_per_day", ascending=False)
    return best_combo, scores_df


# ── Plot ─────────────────────────────────────────────────────────────────────

def plot_route_optimizer(output_path="/mnt/user-data/outputs/reswap_route_optimizer.png", seed=42):
    waypoints, home_base = generate_site(seed=seed)

    print("  Optimizing station placement...")
    best_positions, scores = optimize_station_placement(
        fleet_size=5, n_stations=2, waypoints=waypoints, home_base=home_base, seed=seed)

    print("  Simulating baseline...")
    r_base = simulate_routes(fleet_size=5, use_swap=False, waypoints=waypoints, home_base=home_base, seed=seed)
    print("  Simulating Reswap (default)...")
    r_swap_default = simulate_routes(fleet_size=5, station_positions=[(-600,0),(600,0)],
                                     use_swap=True, waypoints=waypoints, home_base=home_base, seed=seed)
    print("  Simulating Reswap (optimized)...")
    r_swap_opt = simulate_routes(fleet_size=5, station_positions=best_positions,
                                  use_swap=True, waypoints=waypoints, home_base=home_base, seed=seed)

    print("  Fleet sweep...")
    fleet_sizes = [3, 5, 8, 12]
    sweep_base, sweep_swap = [], []
    for n in fleet_sizes:
        rb = simulate_routes(fleet_size=n, use_swap=False, waypoints=waypoints, home_base=home_base, seed=seed, dt=0.5)
        rs = simulate_routes(fleet_size=n, station_positions=best_positions, use_swap=True,
                              waypoints=waypoints, home_base=home_base, seed=seed, dt=0.5)
        sweep_base.append(rb.missions_per_day)
        sweep_swap.append(rs.missions_per_day)

    C_BASE="#4A6FA5"; C_SWAP="#00D48A"; C_OPT="#F0A500"
    C_GRID="#21262D"; C_TEXT="#8B949E"; C_WHITE="#E6EDF3"; C_BG="#161B22"

    fig = plt.figure(figsize=(18, 11), facecolor="#0D1117")
    fig.suptitle("RESWAP — Route Optimizer  |  Updated: Sudheer Handoff (60 packs, 78s swap)",
                 fontsize=16, fontweight="bold", color=C_WHITE, y=0.97)
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.48, wspace=0.38,
                           left=0.06, right=0.97, top=0.91, bottom=0.08)

    def style_ax(ax, title):
        ax.set_facecolor(C_BG)
        ax.tick_params(colors=C_TEXT, labelsize=9)
        ax.xaxis.label.set_color(C_TEXT); ax.yaxis.label.set_color(C_TEXT)
        ax.set_title(title, fontsize=11, fontweight="bold", color=C_WHITE, pad=8)
        for sp in ax.spines.values(): sp.set_edgecolor(C_GRID)
        ax.grid(color=C_GRID, linewidth=0.7, alpha=0.6)

    # 1. Site map
    ax1 = fig.add_subplot(gs[0,0])
    style_ax(ax1, "Site Map — Optimal Station Placement")
    ax1.grid(False)
    circle = plt.Circle((0,0), 2000, fill=False, color=C_GRID, lw=1, ls='--')
    ax1.add_patch(circle)
    ins_x=[w.x for w in waypoints if w.kind=='inspection']
    ins_y=[w.y for w in waypoints if w.kind=='inspection']
    del_x=[w.x for w in waypoints if w.kind=='delivery']
    del_y=[w.y for w in waypoints if w.kind=='delivery']
    ax1.scatter(ins_x, ins_y, c=C_BASE, s=40, zorder=3, label='Inspection', marker='o')
    ax1.scatter(del_x, del_y, c=C_SWAP, s=60, zorder=3, label='Delivery', marker='s')
    ax1.scatter(0, 0, c=C_WHITE, s=100, zorder=5, marker='*', label='Home base')
    for i,(sx,sy) in enumerate(best_positions):
        ax1.scatter(sx, sy, c=C_OPT, s=180, zorder=5, marker='^')
        ax1.annotate(f'STN-{i+1:02d}', (sx,sy), textcoords='offset points',
                     xytext=(8,6), fontsize=8, color=C_OPT)
        cov = plt.Circle((sx,sy), 700, fill=True, alpha=0.07, color=C_OPT)
        ax1.add_patch(cov)
    ax1.set_xlim(-2400,2400); ax1.set_ylim(-2400,2400); ax1.set_aspect('equal')
    ax1.set_xlabel('metres'); ax1.set_ylabel('metres')
    ax1.legend(fontsize=7, labelcolor=C_TEXT, facecolor="#21262D", loc='lower right')

    # 2. 3-way mission comparison
    ax2 = fig.add_subplot(gs[0,1])
    style_ax(ax2, "Missions / Day — 5-Drone Fleet")
    labels=["Baseline\n(no swap)","Reswap\ndefault","Reswap\noptimized"]
    values=[r_base.missions_per_day, r_swap_default.missions_per_day, r_swap_opt.missions_per_day]
    colors=[C_BASE, C_SWAP, C_OPT]
    bars=ax2.bar(labels, values, color=colors, width=0.5)
    ax2.set_ylabel("Missions / day")
    for bar,val in zip(bars,values):
        ax2.text(bar.get_x()+bar.get_width()/2, val+0.5, str(val),
                 ha='center', fontsize=10, color=C_WHITE, fontweight='bold')
    for i,val in enumerate(values[1:],1):
        mult = val/values[0] if values[0]>0 else 0
        ax2.text(i, val+3, f"{mult:.1f}×", ha='center', fontsize=9, color=C_OPT, fontweight='bold')

    # 3. Fleet sweep
    ax3 = fig.add_subplot(gs[0,2])
    style_ax(ax3, "Missions / Day vs Fleet Size")
    x=np.arange(len(fleet_sizes)); w=0.35
    ax3.bar(x-w/2, sweep_base, w, color=C_BASE, label='Baseline')
    ax3.bar(x+w/2, sweep_swap, w, color=C_SWAP, label='Reswap')
    ax3.set_xticks(x); ax3.set_xticklabels([f'{n} drones' for n in fleet_sizes])
    ax3.set_ylabel("Missions / day")
    ax3.legend(fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")
    for i,(b,s) in enumerate(zip(sweep_base,sweep_swap)):
        mult = s/b if b>0 else 0
        ax3.text(x[i]+w/2, s+0.5, f'{mult:.1f}×', ha='center', fontsize=8, color=C_OPT, fontweight='bold')

    # 4. Utilization
    ax4 = fig.add_subplot(gs[1,0])
    style_ax(ax4, "Fleet Utilization % — 5 Drones")
    utils=[r_base.fleet_utilization_pct, r_swap_default.fleet_utilization_pct, r_swap_opt.fleet_utilization_pct]
    bars4=ax4.barh(labels, utils, color=colors, height=0.4)
    ax4.set_xlim(0,105); ax4.set_xlabel("Utilization (%)")
    ax4.axvline(100, color=C_GRID, lw=1, ls='--')
    for bar,val in zip(bars4,utils):
        ax4.text(val+1, bar.get_y()+bar.get_height()/2, f'{val:.0f}%',
                 va='center', fontsize=9, color=C_WHITE)

    # 5. Per-drone breakdown
    ax5 = fig.add_subplot(gs[1,1])
    style_ax(ax5, "Per-Drone Breakdown — Reswap Optimized")
    dl=r_swap_opt.drone_log
    drone_labels=[f'DR-{i+1:02d}' for i in dl.drone_id]
    ax5.barh(drone_labels, dl.time_flying_min, color=C_SWAP, label='Flying', height=0.5)
    ax5.barh(drone_labels, dl.time_grounded_min, left=dl.time_flying_min,
             color=C_BASE, label='Grounded', height=0.5, alpha=0.7)
    ax5.set_xlabel("Minutes in shift")
    ax5.legend(fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")
    for i,row in dl.iterrows():
        ax5.text(row.time_flying_min+row.time_grounded_min+2, i,
                 f'{row.missions}m / {row.swaps}s', va='center', fontsize=8, color=C_TEXT)

    # 6. Placement score distribution
    ax6 = fig.add_subplot(gs[1,2])
    style_ax(ax6, "Station Placement Score Distribution")
    ax6.hist(scores['missions_per_day'], bins=10, color=C_SWAP, alpha=0.75, edgecolor=C_GRID)
    ax6.axvline(scores['missions_per_day'].max(), color=C_OPT, lw=2, ls='--',
                label=f'Best: {scores["missions_per_day"].max()}')
    ax6.axvline(scores['missions_per_day'].min(), color=C_BASE, lw=1.5, ls=':',
                label=f'Worst: {scores["missions_per_day"].min()}')
    ax6.set_xlabel("Missions / day"); ax6.set_ylabel("# of placements")
    ax6.legend(fontsize=8, labelcolor=C_TEXT, facecolor="#21262D")

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor="#0D1117")
    print(f"  Saved → {output_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("RESWAP — Route Optimizer (updated: Sudheer handoff)")
    print(f"Station sockets: {SOCKETS_PER_STATION} | Swap time: {SWAP_TIME_MIN*60:.0f}s | Fee: ${SWAP_FEE_DEFAULT}")
    print("=" * 60)

    waypoints, home_base = generate_site(seed=42)
    print(f"\nSite: {len(waypoints)} waypoints")

    for use_swap in [False, True]:
        r = simulate_routes(fleet_size=5, use_swap=use_swap, waypoints=waypoints, home_base=home_base)
        print(f"\nMode: {r.mode}")
        print(f"  Missions/day:      {r.missions_per_day}")
        print(f"  Fleet utilization: {r.fleet_utilization_pct}%")
        if use_swap:
            print(f"  Total swaps:       {r.total_swaps}")
            print(f"  Revenue (@$12):    ${r.revenue_default:,.0f}")
            print(f"  Multiplier:        {r.missions_per_day / max(simulate_routes(fleet_size=5, use_swap=False, waypoints=waypoints, home_base=home_base).missions_per_day, 1):.1f}×")

    print("\nGenerating chart...")
    plot_route_optimizer()
    print("Done.")
