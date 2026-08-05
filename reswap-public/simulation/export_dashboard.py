"""
Reswap — Dashboard Data Export + HTML Generator

Run this script to:
  1. Execute all simulations
  2. Produce sim_data.json
  3. Bake the JSON into reswap_dashboard.html as inline data

Usage:
  python export_dashboard.py
  python export_dashboard.py --fleet 10 --stations 2 --days 90
"""

import json
import argparse
import sys
import os

from simulation import simulate, breakeven_analysis
from battery_degradation import simulate_station_pack_health, station_degradation_analysis
from constants import (
    SWAP_TIME_MIN, SOCKETS_PER_STATION, MODULES_PER_STATION,
    SOCKETS_PER_MODULE, SWAP_FEE_DEFAULT, OPERATING_HOURS,
)


# ── Data builder ──────────────────────────────────────────────────────────────

def build_sim_data(
    fleet_size: int = 10,
    num_stations: int = 2,
    pack_age_days_stn1: int = 90,
    pack_age_days_stn2: int = 60,
    temp_c_stn1: float = 32.0,
    temp_c_stn2: float = 30.0,
) -> dict:
    print(f"  Simulating fleet ({fleet_size} drones, {num_stations} stations)...")
    r_swap = simulate(fleet_size=fleet_size, num_stations=num_stations, use_swap=True)
    r_base = simulate(fleet_size=fleet_size, num_stations=num_stations, use_swap=False)
    be     = breakeven_analysis(fleet_size=fleet_size, num_stations=num_stations)
    deg    = station_degradation_analysis(temp_c=35.0)

    print("  Simulating pack health...")
    h1 = simulate_station_pack_health(operating_days=pack_age_days_stn1, temp_c=temp_c_stn1, seed=42)
    h2 = simulate_station_pack_health(operating_days=pack_age_days_stn2, temp_c=temp_c_stn2, seed=99)

    def module_summary(df):
        rows = []
        for mod in range(1, MODULES_PER_STATION + 1):
            packs = df[df.module_id == mod]
            rows.append({
                "module":   mod,
                "good":     int((packs.health_status == "good").sum()),
                "degraded": int((packs.health_status == "degraded").sum()),
                "replace":  int((packs.health_status == "replace").sum()),
                "avg_cap":  round(float(packs.capacity_pct.mean()), 1),
            })
        return rows

    timeline      = r_swap.timeline[["time_min","flying","swapping","charging","waiting","missions_total"]].to_dict("records")
    timeline_base = r_base.timeline[["time_min","flying"]].to_dict("records")

    swaps_s1 = r_swap.total_swaps // num_stations
    swaps_s2 = r_swap.total_swaps - swaps_s1

    return {
        "generated_at": "2026-06-28",
        "params": {
            "fleet_size":          fleet_size,
            "num_stations":        num_stations,
            "swap_time_s":         round(SWAP_TIME_MIN * 60),
            "sockets_per_station": SOCKETS_PER_STATION,
            "modules_per_station": MODULES_PER_STATION,
            "sockets_per_module":  SOCKETS_PER_MODULE,
            "swap_fee":            SWAP_FEE_DEFAULT,
            "operating_hours":     OPERATING_HOURS,
        },
        "summary": {
            "missions_reswap":           r_swap.missions_per_day,
            "missions_baseline":         r_base.missions_per_day,
            "multiplier":                round(r_swap.missions_per_day / max(r_base.missions_per_day, 1), 1),
            "utilization_reswap":        r_swap.fleet_utilization_pct,
            "utilization_baseline":      r_base.fleet_utilization_pct,
            "total_swaps":               r_swap.total_swaps,
            "revenue_per_day":           r_swap.revenue_default,
            "saas_per_day":              25.0,
            "daily_revenue_per_station": be["daily_revenue_per_station"],
            "days_to_breakeven":         be["days_to_breakeven"],
            "annual_revenue_per_station":be["annual_revenue_per_station"],
            "pack_cost_per_swap":        deg.cost_per_swap,
            "pack_cost_pct":             round(deg.cost_per_swap / SWAP_FEE_DEFAULT * 100, 2),
        },
        "stations": [
            {
                "id": "STN-01",
                "name": "North pad · Wellhead cluster A",
                "swaps": swaps_s1,
                "arm_status": "ready",
                "pack_age_days": pack_age_days_stn1,
                "temp_c": temp_c_stn1,
                "modules": module_summary(h1),
            },
            {
                "id": "STN-02",
                "name": "South pad · Inspection zone B",
                "swaps": swaps_s2,
                "arm_status": "swapping",
                "pack_age_days": pack_age_days_stn2,
                "temp_c": temp_c_stn2,
                "modules": module_summary(h2),
            },
        ],
        "timeline":          timeline,
        "timeline_baseline": timeline_base,
    }


# ── HTML generator ────────────────────────────────────────────────────────────

DASHBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Reswap — Operator Dashboard</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css"/>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --surface-0:#f0eeea;--surface-1:#f7f6f3;--surface-2:#ffffff;
      --text-primary:#1a1a18;--text-secondary:#5c5b57;--text-muted:#9b9a95;
      --border:rgba(0,0,0,0.09);--border-strong:rgba(0,0,0,0.16);
      --bg-accent:#e8f0fb;--text-accent:#1a5cb8;--fill-accent:#2563eb;
      --bg-success:#e6f4ec;--text-success:#166534;--fill-success:#16a34a;
      --bg-warning:#fef3c7;--text-warning:#92400e;--fill-warning:#d97706;
      --bg-danger:#fce8e8;--text-danger:#991b1b;--fill-danger:#dc2626;
      --radius:8px;--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    }
    @media(prefers-color-scheme:dark){:root{
      --surface-0:#111110;--surface-1:#1c1c1a;--surface-2:#242422;
      --text-primary:#e8e6e1;--text-secondary:#a8a69f;--text-muted:#6b6a65;
      --border:rgba(255,255,255,0.08);--border-strong:rgba(255,255,255,0.14);
      --bg-accent:#0f2a5c;--text-accent:#7aabf7;--fill-accent:#3b82f6;
      --bg-success:#052e16;--text-success:#4ade80;--fill-success:#16a34a;
      --bg-warning:#1c0f00;--text-warning:#fbbf24;--fill-warning:#d97706;
      --bg-danger:#1f0a0a;--text-danger:#f87171;--fill-danger:#dc2626;
    }}
    html,body{height:100%;font-family:var(--font-sans);background:var(--surface-0);color:var(--text-primary);font-size:14px;line-height:1.5}
    .app{display:grid;grid-template-columns:210px 1fr;grid-template-rows:48px 1fr;height:100vh;overflow:hidden}
    .topbar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--surface-2);border-bottom:0.5px solid var(--border);z-index:10}
    .logo{font-size:15px;font-weight:600;color:var(--text-primary);letter-spacing:-0.4px}
    .logo span{color:var(--fill-accent)}
    .site-badge{font-size:11px;color:var(--text-muted);background:var(--surface-1);border:0.5px solid var(--border);border-radius:var(--radius);padding:3px 9px;margin-left:10px}
    .topbar-r{display:flex;align-items:center;gap:10px}
    .live-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;display:inline-block}
    .shift-time{font-size:12px;font-weight:500;color:var(--text-primary);font-variant-numeric:tabular-nums}
    .shift-lbl{font-size:12px;color:var(--text-secondary)}
    .sidebar{background:var(--surface-1);border-right:0.5px solid var(--border);padding:14px 10px;display:flex;flex-direction:column;gap:2px;overflow-y:auto}
    .nsec{font-size:10px;font-weight:500;color:var(--text-muted);padding:12px 10px 4px;letter-spacing:.08em;text-transform:uppercase}
    .nav{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:var(--radius);cursor:pointer;font-size:13px;color:var(--text-secondary);user-select:none;transition:background .1s}
    .nav:hover{background:var(--surface-2);color:var(--text-primary)}
    .nav.active{background:var(--bg-accent);color:var(--text-accent);font-weight:500}
    .nav i{font-size:16px;flex-shrink:0}
    .nav-spacer{flex:1}
    .main{padding:20px;overflow-y:auto;display:flex;flex-direction:column;gap:16px}
    .metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
    .mc{background:var(--surface-1);border-radius:var(--radius);padding:14px 16px}
    .mc-lbl{font-size:11px;color:var(--text-muted);margin-bottom:6px}
    .mc-val{font-size:24px;font-weight:500;color:var(--text-primary);line-height:1;font-variant-numeric:tabular-nums}
    .mc-sub{font-size:11px;margin-top:5px}
    .up{color:var(--text-success)} .muted{color:var(--text-secondary)}
    .sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
    .sec-title{font-size:13px;font-weight:500;color:var(--text-primary)}
    .sec-link{font-size:12px;color:var(--text-accent);cursor:pointer}
    .fleet-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
    .dc{background:var(--surface-2);border:0.5px solid var(--border);border-radius:10px;padding:10px 11px;display:flex;flex-direction:column;gap:7px;cursor:pointer;transition:border-color .15s}
    .dc:hover{border-color:var(--border-strong)}
    .dc-id{font-size:11px;font-weight:500;color:var(--text-primary)}
    .pill{font-size:10px;padding:2px 7px;border-radius:999px;display:inline-block;width:fit-content}
    .p-flying{background:var(--bg-accent);color:var(--text-accent)}
    .p-swapping{background:var(--bg-warning);color:var(--text-warning)}
    .p-charging{background:var(--bg-success);color:var(--text-success)}
    .p-waiting{background:var(--surface-1);color:var(--text-muted);border:0.5px solid var(--border)}
    .bb{height:4px;background:var(--surface-0);border-radius:2px;overflow:hidden}
    .bf{height:100%;border-radius:2px}
    .bfull{background:#22c55e} .bmid{background:var(--fill-warning)} .blow{background:var(--fill-danger)}
    .dc-batt{font-size:10px;color:var(--text-muted)}
    .two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    .panel{background:var(--surface-2);border:0.5px solid var(--border);border-radius:10px;padding:14px 16px}
    .stn-row{display:flex;align-items:flex-start;justify-content:space-between;padding:10px 0;border-bottom:0.5px solid var(--border)}
    .stn-row:last-child{border-bottom:none}
    .stn-name{font-size:13px;font-weight:500;color:var(--text-primary)}
    .stn-loc{font-size:11px;color:var(--text-muted);margin-top:1px}
    .arm-status{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--text-secondary);margin-top:5px}
    .arm-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
    .stn-r{display:flex;align-items:center;gap:14px}
    .stn-sv{font-size:14px;font-weight:500;color:var(--text-primary);text-align:right}
    .stn-sl{font-size:10px;color:var(--text-muted);text-align:right}
    .mod-wrap{display:flex;align-items:flex-start;gap:4px;margin-top:5px}
    .mod-lbl{font-size:9px;color:var(--text-muted);width:16px;flex-shrink:0;padding-top:1px}
    .mod-socks{display:flex;gap:2px;flex-wrap:wrap;max-width:160px}
    .sock{width:10px;height:10px;border-radius:1px;flex-shrink:0}
    .s-c{background:#22c55e} .s-d{background:var(--fill-warning)} .s-r{background:var(--fill-danger)}
    .s-e{background:var(--surface-1);border:0.5px solid var(--border)}
    .pack-legend{display:flex;align-items:center;gap:10px;font-size:10px;color:var(--text-muted);margin-top:10px;padding-top:8px;border-top:0.5px solid var(--border)}
    .leg-item{display:flex;align-items:center;gap:3px}
    .leg-dot{width:8px;height:8px;border-radius:1px}
    .mission-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:0.5px solid var(--border);font-size:12px}
    .mission-row:last-child{border-bottom:none}
    .m-drone{font-weight:500;color:var(--text-primary)}
    .m-type{font-size:11px;color:var(--text-muted)}
    .m-time{font-size:11px;color:var(--text-muted)}
    .rev-row{display:flex;align-items:center;gap:10px;padding:6px 0}
    .rev-lbl{font-size:12px;color:var(--text-secondary);width:72px;flex-shrink:0}
    .rev-bar{flex:1;height:6px;background:var(--surface-1);border-radius:3px;overflow:hidden}
    .rb-fill{height:100%;border-radius:3px}
    .rev-val{font-size:12px;font-weight:500;color:var(--text-primary);width:60px;text-align:right;flex-shrink:0;font-variant-numeric:tabular-nums}
    .rev-total{border-top:0.5px solid var(--border);margin-top:8px;padding-top:10px;display:flex;justify-content:space-between;align-items:baseline}
    .be-sec{border-top:0.5px solid var(--border);margin-top:10px;padding-top:10px}
    .be-bar-wrap{display:flex;align-items:center;gap:8px;margin-top:5px}
    .be-bar{flex:1;height:5px;background:var(--surface-1);border-radius:3px;overflow:hidden}
    .be-fill-el{height:100%;border-radius:3px;background:var(--fill-accent)}
    .be-txt{font-size:11px;color:var(--text-secondary);white-space:nowrap}
    .pack-cost-row{border-top:0.5px solid var(--border);margin-top:8px;padding-top:8px;display:flex;justify-content:space-between;align-items:center}
    .chart-wrap{position:relative;height:80px;margin-top:4px}
    canvas{display:block}
    .data-ts{font-size:10px;color:var(--text-muted);text-align:right;margin-top:4px}
  </style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div style="display:flex;align-items:center">
      <div class="logo">re<span>swap</span></div>
      <div class="site-badge" id="site-badge">Permian Basin · Alpha Site</div>
    </div>
    <div class="topbar-r">
      <span class="live-dot"></span>
      <span class="shift-lbl">Shift elapsed</span>
      <span class="shift-time" id="shift-elapsed">00:00:00</span>
    </div>
  </header>

  <nav class="sidebar">
    <div class="nav active"><i class="ti ti-layout-dashboard" aria-hidden="true"></i> Overview</div>
    <div class="nav"><i class="ti ti-drone" aria-hidden="true"></i> Fleet</div>
    <div class="nav"><i class="ti ti-battery-charging" aria-hidden="true"></i> Batteries</div>
    <div class="nsec">Operations</div>
    <div class="nav"><i class="ti ti-route" aria-hidden="true"></i> Missions</div>
    <div class="nav"><i class="ti ti-map-pin" aria-hidden="true"></i> Stations</div>
    <div class="nsec">Analytics</div>
    <div class="nav"><i class="ti ti-chart-line" aria-hidden="true"></i> Revenue</div>
    <div class="nav"><i class="ti ti-report-analytics" aria-hidden="true"></i> Reports</div>
    <div class="nav-spacer"></div>
    <div class="nav"><i class="ti ti-settings" aria-hidden="true"></i> Settings</div>
  </nav>

  <main class="main">
    <div class="metrics">
      <div class="mc">
        <div class="mc-lbl">Missions today</div>
        <div class="mc-val" id="m-mis">—</div>
        <div class="mc-sub up" id="m-mis-sub">—</div>
      </div>
      <div class="mc">
        <div class="mc-lbl">Fleet utilization</div>
        <div class="mc-val" id="m-util">—</div>
        <div class="mc-sub up" id="m-util-sub">—</div>
      </div>
      <div class="mc">
        <div class="mc-lbl">Total swaps</div>
        <div class="mc-val" id="m-swaps">—</div>
        <div class="mc-sub muted" id="m-swaps-sub">—</div>
      </div>
      <div class="mc">
        <div class="mc-lbl">Revenue today</div>
        <div class="mc-val" id="m-rev">—</div>
        <div class="mc-sub muted" id="m-rev-sub">—</div>
      </div>
    </div>

    <div>
      <div class="sec-hdr">
        <div class="sec-title">Fleet status</div>
        <div class="sec-link">view all →</div>
      </div>
      <div class="fleet-grid" id="fleet-grid"></div>
    </div>

    <div class="two">
      <div>
        <div class="sec-hdr">
          <div class="sec-title" id="stn-panel-title">Stations — pack health</div>
        </div>
        <div class="panel" style="padding:10px 14px" id="stn-panel"></div>
      </div>

      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <div class="sec-hdr">
            <div class="sec-title">Drones in air — sim timeline</div>
          </div>
          <div class="panel" style="padding:10px 14px">
            <div class="chart-wrap"><canvas id="timeline-chart"></canvas></div>
            <div style="display:flex;gap:14px;margin-top:6px">
              <div style="display:flex;align-items:center;gap:5px;font-size:10px;color:var(--text-muted)">
                <div style="width:20px;height:2px;background:#22c55e"></div>Reswap
              </div>
              <div style="display:flex;align-items:center;gap:5px;font-size:10px;color:var(--text-muted)">
                <div style="width:20px;height:2px;background:#4A6FA5"></div>Baseline
              </div>
            </div>
          </div>
        </div>
        <div>
          <div class="sec-hdr"><div class="sec-title">Revenue</div></div>
          <div class="panel">
            <div class="rev-row">
              <div class="rev-lbl">Swap fees</div>
              <div class="rev-bar"><div class="rb-fill" id="rb-swap" style="background:var(--fill-accent);width:0%"></div></div>
              <div class="rev-val" id="rr-swap">—</div>
            </div>
            <div class="rev-row">
              <div class="rev-lbl">Fleet SaaS</div>
              <div class="rev-bar"><div class="rb-fill" id="rb-saas" style="background:var(--fill-success);width:0%"></div></div>
              <div class="rev-val" id="rr-saas">—</div>
            </div>
            <div class="rev-total">
              <div style="font-size:12px;color:var(--text-muted)">Daily total</div>
              <div style="font-size:16px;font-weight:500;color:var(--text-primary)" id="rev-total">—</div>
            </div>
            <div class="be-sec">
              <div style="font-size:11px;color:var(--text-muted)">Break-even progress</div>
              <div class="be-bar-wrap">
                <div class="be-bar"><div class="be-fill-el" id="be-fill" style="width:0%"></div></div>
                <div class="be-txt" id="be-txt">—</div>
              </div>
            </div>
            <div class="pack-cost-row">
              <div style="font-size:11px;color:var(--text-muted)">Pack cost per swap</div>
              <div style="font-size:11px;font-weight:500;color:var(--text-success)" id="pack-cost">—</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="data-ts" id="data-ts"></div>
  </main>
</div>

<script>
const SIM = __SIM_DATA__;

function fmt$(n){return '$'+Number(n).toLocaleString()}
function fmtPct(n){return Math.round(n)+'%'}
function battCls(p){return p>40?'bfull':p>15?'bmid':'blow'}

function buildFleet(){
  const p = SIM.params;
  const statuses = ['flying','flying','swapping','charging','flying','flying','charging','flying','swapping','charging'];
  const batts    = [72,55,3,61,88,40,100,65,1,30];
  const n = p.fleet_size;
  let html = '';
  for(let i=0;i<n;i++){
    const id  = `DR-${String(i+1).padStart(2,'0')}`;
    const st  = statuses[i % statuses.length];
    const bat = batts[i % batts.length];
    html += `<div class="dc">
      <div class="dc-id">${id}</div>
      <div class="pill p-${st}">${st}</div>
      <div class="bb"><div class="bf ${battCls(bat)}" style="width:${bat}%"></div></div>
      <div class="dc-batt">${bat}%</div>
    </div>`;
  }
  document.getElementById('fleet-grid').innerHTML = html;
}

function buildStations(){
  const p = SIM.params;
  document.getElementById('stn-panel-title').textContent =
    `Stations — pack health (${p.modules_per_station} modules × ${p.sockets_per_module})`;

  let html = '';
  SIM.stations.forEach((stn, si) => {
    const armColor = stn.arm_status === 'ready' ? '#22c55e' : 'var(--fill-warning)';
    const armLabel = stn.arm_status === 'ready' ? 'Arm ready' : 'Swapping';

    let modHtml = '';
    stn.modules.forEach(m => {
      let socks = '';
      for(let i=0;i<m.good;i++)     socks += `<div class="sock s-c" title="Good ${m.avg_cap}%"></div>`;
      for(let i=0;i<m.degraded;i++) socks += `<div class="sock s-d" title="Degraded"></div>`;
      for(let i=0;i<m.replace;i++)  socks += `<div class="sock s-r" title="Replace"></div>`;
      const empty = p.sockets_per_module - m.good - m.degraded - m.replace;
      for(let i=0;i<empty;i++)      socks += `<div class="sock s-e"></div>`;
      modHtml += `<div class="mod-wrap">
        <div class="mod-lbl">M${m.module}</div>
        <div class="mod-socks">${socks}</div>
      </div>`;
    });

    html += `<div class="stn-row">
      <div>
        <div class="stn-name">${stn.id}</div>
        <div class="stn-loc">${stn.name}</div>
        <div class="arm-status"><div class="arm-dot" style="background:${armColor}"></div>${armLabel}</div>
        ${modHtml}
      </div>
      <div class="stn-r">
        <div>
          <div class="stn-sv">${stn.swaps}</div>
          <div class="stn-sl">swaps</div>
        </div>
      </div>
    </div>`;
  });

  html += `<div class="pack-legend">
    <div class="leg-item"><div class="leg-dot" style="background:#22c55e"></div>Good ≥90%</div>
    <div class="leg-item"><div class="leg-dot" style="background:var(--fill-warning)"></div>Degraded</div>
    <div class="leg-item"><div class="leg-dot" style="background:var(--fill-danger)"></div>Replace</div>
  </div>`;

  document.getElementById('stn-panel').innerHTML = html;
}

function buildMetrics(){
  const s = SIM.summary;
  const p = SIM.params;

  document.getElementById('m-mis').textContent = s.missions_reswap;
  document.getElementById('m-mis-sub').textContent =
    `↑ vs ${s.missions_baseline} baseline (${s.multiplier}×)`;

  document.getElementById('m-util').textContent = fmtPct(s.utilization_reswap);
  document.getElementById('m-util-sub').textContent =
    `↑ from ${fmtPct(s.utilization_baseline)} no-swap`;

  document.getElementById('m-swaps').textContent = s.total_swaps;
  document.getElementById('m-swaps-sub').textContent =
    `${SIM.stations.length} stations · ${p.sockets_per_station} packs ea.`;

  document.getElementById('m-rev').textContent = fmt$(s.revenue_per_day);
  document.getElementById('m-rev-sub').textContent =
    `@ $${p.swap_fee}/swap`;
}

function buildRevenue(){
  const s = SIM.summary;
  const swapRev  = s.revenue_per_day;
  const saasRev  = s.saas_per_day;
  const total    = swapRev + saasRev;
  const maxRev   = swapRev + saasRev;
  const beTotal  = s.daily_revenue_per_station;
  const bePct    = Math.min(Math.round(total / beTotal / s.days_to_breakeven * 100 * s.days_to_breakeven), 100);

  document.getElementById('rr-swap').textContent = fmt$(swapRev);
  document.getElementById('rr-saas').textContent = fmt$(saasRev);
  document.getElementById('rev-total').textContent = fmt$(total);
  document.getElementById('rb-swap').style.width = Math.round(swapRev/maxRev*85)+'%';
  document.getElementById('rb-saas').style.width = Math.round(saasRev/maxRev*85)+'%';

  const beDay = Math.max(1, Math.round(s.days_to_breakeven));
  document.getElementById('be-fill').style.width = Math.min(Math.round(1/beDay*100),100)+'%';
  document.getElementById('be-txt').textContent = `Day 1 of ~${beDay}`;

  document.getElementById('pack-cost').textContent =
    `$${s.pack_cost_per_swap.toFixed(4)} (${s.pack_cost_pct}% of fee)`;
}

function buildTimeline(){
  const canvas = document.getElementById('timeline-chart');
  const wrap   = canvas.parentElement;
  canvas.width  = wrap.clientWidth || 300;
  canvas.height = 80;
  const ctx = canvas.getContext('2d');
  const tl  = SIM.timeline;
  const tlb = SIM.timeline_baseline;
  const fleet = SIM.params.fleet_size;

  const isDark = window.matchMedia('(prefers-color-scheme:dark)').matches;
  const gridColor  = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';
  const labelColor = isDark ? '#6b6a65' : '#9b9a95';

  const W = canvas.width, H = canvas.height;
  const padL=28, padR=8, padT=6, padB=18;
  const cW = W-padL-padR, cH = H-padT-padB;

  function xOf(i, arr){ return padL + (i/(arr.length-1))*cW }
  function yOf(v){ return padT + cH - (v/fleet)*cH }

  ctx.clearRect(0,0,W,H);

  // Grid lines
  ctx.strokeStyle = gridColor; ctx.lineWidth = 0.5;
  [0, Math.round(fleet/2), fleet].forEach(v => {
    const y = yOf(v);
    ctx.beginPath(); ctx.moveTo(padL,y); ctx.lineTo(W-padR,y); ctx.stroke();
    ctx.fillStyle = labelColor;
    ctx.font = '9px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(v, padL-3, y+3);
  });

  // X labels (hours)
  ctx.textAlign = 'center'; ctx.fillStyle = labelColor; ctx.font='9px sans-serif';
  [0,2,4,6,8,10].forEach(h => {
    const idx = Math.round(h/10*(tl.length-1));
    const x = xOf(idx, tl);
    ctx.fillText(h+'h', x, H-2);
  });

  function drawLine(arr, key, color, lw=1.5){
    ctx.beginPath(); ctx.strokeStyle=color; ctx.lineWidth=lw;
    arr.forEach((pt,i)=>{ const x=xOf(i,arr), y=yOf(pt[key]||0); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); });
    ctx.stroke();
  }

  drawLine(tlb, 'flying', '#4A6FA5', 1.2);
  drawLine(tl,  'flying', '#22c55e', 2);
}

const SHIFT_START=(()=>{const d=new Date();d.setHours(10,0,0,0);return d;})();
let tickSwaps = SIM.summary.total_swaps;

function tick(){
  const el=Date.now()-SHIFT_START;
  const h=String(Math.floor(el/3600000)).padStart(2,'0');
  const m=String(Math.floor((el%3600000)/60000)).padStart(2,'0');
  const s=String(Math.floor((el%60000)/1000)).padStart(2,'0');
  document.getElementById('shift-elapsed').textContent=`${h}:${m}:${s}`;
}

document.querySelectorAll('.nav').forEach(n=>{
  n.addEventListener('click',()=>{
    document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));
    n.classList.add('active');
  });
});

document.getElementById('data-ts').textContent =
  `Simulation data: ${SIM.generated_at}  ·  Fleet: ${SIM.params.fleet_size} drones  ·  Swap time: ${SIM.params.swap_time_s}s  ·  Fee: $${SIM.params.swap_fee}/swap`;

buildMetrics();
buildFleet();
buildStations();
buildRevenue();
buildTimeline();
tick();
setInterval(tick, 1000);
</script>
</body>
</html>
"""


def generate_dashboard(data: dict, output_path: str):
    json_str = json.dumps(data, separators=(",", ":"))
    html = DASHBOARD_TEMPLATE.replace("__SIM_DATA__", json_str)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"  Dashboard → {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Reswap dashboard exporter")
    parser.add_argument("--fleet",    type=int,   default=10,  help="Fleet size")
    parser.add_argument("--stations", type=int,   default=2,   help="Number of stations")
    parser.add_argument("--days1",    type=int,   default=90,  help="STN-01 pack age (days)")
    parser.add_argument("--days2",    type=int,   default=60,  help="STN-02 pack age (days)")
    parser.add_argument("--temp1",    type=float, default=32.0,help="STN-01 temp (°C)")
    parser.add_argument("--temp2",    type=float, default=30.0,help="STN-02 temp (°C)")
    parser.add_argument("--json",     default="sim_data.json", help="JSON output path")
    parser.add_argument("--html",     default="/mnt/user-data/outputs/reswap_dashboard.html",
                        help="HTML output path")
    args = parser.parse_args()

    print("=" * 60)
    print("Reswap — Dashboard Export")
    print("=" * 60)

    data = build_sim_data(
        fleet_size=args.fleet,
        num_stations=args.stations,
        pack_age_days_stn1=args.days1,
        pack_age_days_stn2=args.days2,
        temp_c_stn1=args.temp1,
        temp_c_stn2=args.temp2,
    )

    print(f"  Writing JSON → {args.json}")
    with open(args.json, "w") as f:
        json.dump(data, f, indent=2)

    print("  Generating dashboard HTML...")
    generate_dashboard(data, args.html)

    print("\nDone.")
    print(f"  Missions:     {data['summary']['missions_reswap']} ({data['summary']['multiplier']}× baseline)")
    print(f"  Utilization:  {data['summary']['utilization_reswap']}%")
    print(f"  Revenue/day:  ${data['summary']['revenue_per_day']:,.0f}")
    print(f"  Break-even:   {data['summary']['days_to_breakeven']} days")


if __name__ == "__main__":
    main()
