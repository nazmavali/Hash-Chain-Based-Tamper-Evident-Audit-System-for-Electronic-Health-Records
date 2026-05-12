import os
import csv
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


RESULTS_DIR   = os.path.join(os.path.dirname(__file__), 'results')
CSV_OFF       = os.path.join(RESULTS_DIR, 'benchmark_audit_off.csv')
CSV_ON        = os.path.join(RESULTS_DIR, 'benchmark_audit_on.csv')
CSV_SUMMARY   = os.path.join(RESULTS_DIR, 'overhead_summary_table.csv')
CHART_LATENCY = os.path.join(RESULTS_DIR, 'chart_latency_overhead.png')
CHART_TP      = os.path.join(RESULTS_DIR, 'chart_throughput_comparison.png')
CHART_OH_PCT  = os.path.join(RESULTS_DIR, 'chart_overhead_pct.png')

WORKLOADS     = ['bulk_insert', 'update', 'delete']
WORKLOAD_LABELS = {
    'bulk_insert': 'Bulk Insert',
    'update':      'Update',
    'delete':      'Delete',
}

COLORS = {
    'off': '#2196F3',   
    'on':  '#F44336',   
}

WORKLOAD_COLORS = {
    'bulk_insert': '#E91E63',
    'update':      '#FF9800',
    'delete':      '#9C27B0',
}


def load_csv(filepath):
    """Load a benchmark CSV into a dict keyed by (dataset_size, workload)."""
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)
    data = {}
    with open(filepath, newline='') as f:
        for row in csv.DictReader(f):
            key = (int(float(row['dataset_size'])), row['workload'].strip())
            data[key] = {
                'total_time_s':       float(row['total_time_s']),
                'throughput_ops_sec': float(row['throughput_ops_sec']),
                'avg_latency_ms':     float(row['avg_latency_ms']),
            }
    return data


def compute_overhead(off_data, on_data):
    """
    Compute overhead metrics for every (dataset_size, workload) combination.

    Returns a list of dicts with:
        dataset_size, workload,
        off_latency_ms, on_latency_ms, latency_overhead_pct,
        off_throughput,  on_throughput,  throughput_drop_pct
    """
    results = []
    sizes = sorted(set(k[0] for k in off_data))

    for size in sizes:
        for wl in WORKLOADS:
            key = (size, wl)
            if key not in off_data or key not in on_data:
                continue

            off_lat = off_data[key]['avg_latency_ms']
            on_lat  = on_data[key]['avg_latency_ms']
            off_tp  = off_data[key]['throughput_ops_sec']
            on_tp   = on_data[key]['throughput_ops_sec']

            lat_oh  = (on_lat - off_lat) / off_lat * 100
            tp_drop = (off_tp - on_tp)   / off_tp  * 100

            results.append({
                'dataset_size':         size,
                'workload':             wl,
                'off_latency_ms':       round(off_lat, 6),
                'on_latency_ms':        round(on_lat,  6),
                'latency_overhead_pct': round(lat_oh,  2),
                'off_throughput':       round(off_tp,  2),
                'on_throughput':        round(on_tp,   2),
                'throughput_drop_pct':  round(tp_drop, 2),
            })
    return results


def print_summary_table(rows):
    header = (
        f"{'Dataset':>10} {'Workload':>12} "
        f"{'OFF lat(ms)':>12} {'ON lat(ms)':>12} {'Lat OH%':>10} "
        f"{'OFF tp':>12} {'ON tp':>12} {'TP drop%':>10}"
    )
    sep = "─" * len(header)
    print("\n" + "═" * len(header))
    print("  PERFORMANCE OVERHEAD SUMMARY")
    print("═" * len(header))
    print(header)
    print(sep)
    for r in rows:
        print(
            f"{r['dataset_size']:>10,} {r['workload']:>12} "
            f"{r['off_latency_ms']:>12.6f} {r['on_latency_ms']:>12.6f} "
            f"{r['latency_overhead_pct']:>+9.1f}% "
            f"{r['off_throughput']:>12,.1f} {r['on_throughput']:>12,.1f} "
            f"{r['throughput_drop_pct']:>9.1f}%"
        )
    print("═" * len(header) + "\n")


def save_summary_csv(rows):
    fieldnames = [
        'dataset_size', 'workload',
        'off_latency_ms', 'on_latency_ms', 'latency_overhead_pct',
        'off_throughput', 'on_throughput', 'throughput_drop_pct',
    ]
    with open(CSV_SUMMARY, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Summary table saved → {CSV_SUMMARY}")


def chart_latency_overhead(rows):
    """
    Grouped bar chart: OFF vs ON average latency per workload,
    one group of bars per dataset size.
    """
    sizes = sorted(set(r['dataset_size'] for r in rows))
    size_labels = [f"{s:,}" for s in sizes]
    x = np.arange(len(sizes))
    bar_width = 0.12
    offsets = np.linspace(-bar_width * 1.5, bar_width * 1.5, len(WORKLOADS) * 2)

    fig, ax = plt.subplots(figsize=(13, 6))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')

    idx = 0
    for wl in WORKLOADS:
        wl_rows = [r for r in rows if r['workload'] == wl]
        wl_rows.sort(key=lambda r: r['dataset_size'])
        off_lats = [r['off_latency_ms'] for r in wl_rows]
        on_lats  = [r['on_latency_ms']  for r in wl_rows]
        base_color = WORKLOAD_COLORS[wl]

        ax.bar(x + offsets[idx],     off_lats, bar_width,
               label=f'{WORKLOAD_LABELS[wl]} OFF',
               color=base_color, alpha=0.5, edgecolor='white', linewidth=0.5)
        ax.bar(x + offsets[idx + 1], on_lats,  bar_width,
               label=f'{WORKLOAD_LABELS[wl]} ON',
               color=base_color, alpha=1.0, edgecolor='white', linewidth=0.5)
        idx += 2

    ax.set_xlabel('Dataset Size (total ops)', color='white', fontsize=11)
    ax.set_ylabel('Avg Latency (ms)', color='white', fontsize=11)
    ax.set_title('Avg Latency: Audit OFF vs Audit ON\nby Workload and Dataset Size',
                 color='white', fontsize=13, fontweight='bold', pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(size_labels, color='white')
    ax.tick_params(colors='white')
    ax.spines['bottom'].set_color('#444')
    ax.spines['left'].set_color('#444')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.yaxis.grid(True, color='#333', linestyle='--', linewidth=0.6)
    ax.set_axisbelow(True)
    legend = ax.legend(loc='upper left', fontsize=8,
                       facecolor='#1a1a2e', edgecolor='#444',
                       labelcolor='white', ncol=3)
    plt.tight_layout()
    plt.savefig(CHART_LATENCY, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Chart 1 saved       → {CHART_LATENCY}")


def chart_throughput_comparison(rows):
    """
    Line chart: OFF vs ON throughput (ops/sec) per workload across dataset sizes.
    Solid line = OFF, dashed line = ON.
    """
    sizes = sorted(set(r['dataset_size'] for r in rows))
    size_labels = [f"{s:,}" for s in sizes]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
    fig.patch.set_facecolor('#0d1117')
    fig.suptitle('Throughput (ops/sec): Audit OFF vs Audit ON',
                 color='white', fontsize=13, fontweight='bold', y=1.02)

    for ax, wl in zip(axes, WORKLOADS):
        ax.set_facecolor('#161b22')
        wl_rows = sorted([r for r in rows if r['workload'] == wl],
                         key=lambda r: r['dataset_size'])
        off_tp = [r['off_throughput'] for r in wl_rows]
        on_tp  = [r['on_throughput']  for r in wl_rows]
        x      = list(range(len(sizes)))
        color  = WORKLOAD_COLORS[wl]

        ax.plot(x, off_tp, 'o-', color=color, alpha=0.6, linewidth=2,
                markersize=7, label='Audit OFF')
        ax.plot(x, on_tp,  's--', color=color, alpha=1.0, linewidth=2,
                markersize=7, label='Audit ON')

        ax.fill_between(x, on_tp, off_tp, alpha=0.12, color=color)

        ax.set_title(WORKLOAD_LABELS[wl], color='white', fontsize=11,
                     fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(size_labels, color='white', fontsize=8, rotation=15)
        ax.tick_params(colors='white')
        ax.set_xlabel('Dataset Size', color='white', fontsize=9)
        ax.set_ylabel('Throughput (ops/sec)', color='white', fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f'{v:,.0f}'))
        ax.spines['bottom'].set_color('#444')
        ax.spines['left'].set_color('#444')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.grid(True, color='#2a2a2a', linestyle='--', linewidth=0.6)
        ax.set_axisbelow(True)
        ax.legend(fontsize=8, facecolor='#1a1a2e',
                  edgecolor='#444', labelcolor='white')

    plt.tight_layout()
    plt.savefig(CHART_TP, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Chart 2 saved       → {CHART_TP}")


def chart_overhead_pct(rows):
    """
    Line chart: latency overhead % per workload across dataset sizes.
    Shows how overhead grows as the audit_log fills up.
    """
    sizes = sorted(set(r['dataset_size'] for r in rows))
    size_labels = [f"{s:,}" for s in sizes]
    x = list(range(len(sizes)))

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#161b22')

    for wl in WORKLOADS:
        wl_rows = sorted([r for r in rows if r['workload'] == wl],
                         key=lambda r: r['dataset_size'])
        oh_pcts = [r['latency_overhead_pct'] for r in wl_rows]
        color   = WORKLOAD_COLORS[wl]

        ax.plot(x, oh_pcts, 'o-', color=color, linewidth=2.5,
                markersize=8, label=WORKLOAD_LABELS[wl])

        for xi, pct in zip(x, oh_pcts):
            ax.annotate(f'{pct:.0f}%',
                        xy=(xi, pct),
                        xytext=(0, 10),
                        textcoords='offset points',
                        ha='center', fontsize=8, color=color)

    ax.set_xlabel('Dataset Size (total ops)', color='white', fontsize=11)
    ax.set_ylabel('Latency Overhead %\n(ON − OFF) / OFF × 100',
                  color='white', fontsize=11)
    ax.set_title('Latency Overhead % vs Dataset Size\n'
                 'Shows how audit cost scales as data volume grows',
                 color='white', fontsize=13, fontweight='bold', pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(size_labels, color='white')
    ax.tick_params(colors='white')
    ax.spines['bottom'].set_color('#444')
    ax.spines['left'].set_color('#444')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.yaxis.grid(True, color='#2a2a2a', linestyle='--', linewidth=0.6)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f'{v:.0f}%'))
    legend = ax.legend(fontsize=10, facecolor='#1a1a2e',
                       edgecolor='#444', labelcolor='white')
    plt.tight_layout()
    plt.savefig(CHART_OH_PCT, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Chart 3 saved       → {CHART_OH_PCT}")


def main():
    print("\n" + "=" * 60)
    print("  STEP 9 — RESULTS ANALYSIS & CHART GENERATION")
    print("=" * 60)

    print("\nLoading CSVs...")
    off_data = load_csv(CSV_OFF)
    on_data  = load_csv(CSV_ON)
    print(f"  Loaded {len(off_data)} audit-OFF rows")
    print(f"  Loaded {len(on_data)}  audit-ON  rows")

    print("\nComputing overhead metrics...")
    summary_rows = compute_overhead(off_data, on_data)

    print_summary_table(summary_rows)

    print("Saving outputs...")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    save_summary_csv(summary_rows)
    chart_latency_overhead(summary_rows)
    chart_throughput_comparison(summary_rows)
    chart_overhead_pct(summary_rows)

    print("\n" + "=" * 60)
    print("  ANALYSIS COMPLETE")
    print("=" * 60 + "\n")

    return summary_rows


if __name__ == "__main__":
    main()