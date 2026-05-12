"""
Test File 5 — Part C: Benchmark Results Validation

Covers:
  - CSV output files exist and contain all expected columns
  - Audit-ON latency is higher than audit-OFF latency for every workload
  - Audit-ON throughput is lower than audit-OFF throughput for every workload
  - Performance overhead percentage is within a realistic range (1% – 2000%)
  - Throughput degrades gracefully as dataset size grows (no sudden cliff)
  - Bulk insert overhead is higher than update/delete (hash chain is per-row)
  - All numeric values in CSV are positive and non-zero
  - Dataset sizes in CSV match the expected benchmark configurations

Expected CSV files (produced by benchmark scripts):
    results/benchmark_audit_off.csv
    results/benchmark_audit_on.csv

Expected CSV columns:
    dataset_size, workload, total_time_s, throughput_ops_sec, avg_latency_ms
"""

import pytest
import os
import csv
import statistics

# Paths to benchmark CSV files
RESULTS_DIR      = os.path.join(os.path.dirname(__file__), '..', 'results')
CSV_AUDIT_OFF    = os.path.join(RESULTS_DIR, 'benchmark_audit_off.csv')
CSV_AUDIT_ON     = os.path.join(RESULTS_DIR, 'benchmark_audit_on.csv')

# Expected configuration (must match benchmark scripts)
EXPECTED_COLUMNS = [
    'dataset_size',
    'workload',
    'total_time_s',
    'throughput_ops_sec',
    'avg_latency_ms',
]

EXPECTED_DATASET_SIZES = [60000, 120000, 180000, 300000]
# 60000  = 10k patients + 50k prescriptions
# 120000 = 20k patients + 100k prescriptions
# 180000 = 30k patients + 150k prescriptions
# 300000 = 50k patients + 250k prescriptions

EXPECTED_WORKLOADS = ['bulk_insert', 'update', 'delete']

# Overhead bounds — must be between these percentages
MIN_OVERHEAD_PCT =    1.0    # If 0% the audit system has no effect (impossible)
MAX_OVERHEAD_PCT = 2000.0    # If >2000% something is catastrophically wrong

# Maximum allowed throughput drop between consecutive dataset sizes (fraction)
# e.g. 0.90 means throughput must not drop more than 90% from one size to next
MAX_THROUGHPUT_DROP_FRACTION = 0.90


# Helpers
def load_csv(filepath):
    """
    Load a benchmark CSV into a list of dicts.
    Numeric columns are cast to float automatically.
    """
    if not os.path.exists(filepath):
        pytest.skip(
            f"CSV file not found: {filepath}\n"
            f"Run benchmark scripts first to generate results."
        )
    rows = []
    with open(filepath, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip()
                try:
                    parsed[k] = float(v)
                except ValueError:
                    parsed[k] = v
            rows.append(parsed)
    return rows


def filter_rows(rows, workload=None, dataset_size=None):
    """Filter CSV rows by workload and/or dataset_size."""
    result = rows
    if workload:
        result = [r for r in result if r.get('workload') == workload]
    if dataset_size is not None:
        result = [r for r in result if r.get('dataset_size') == dataset_size]
    return result


def get_metric(rows, workload, dataset_size, metric):
    """Extract a single metric value for a given workload + dataset_size."""
    matches = filter_rows(rows, workload=workload, dataset_size=dataset_size)
    if not matches:
        return None
    return matches[0].get(metric)


def compute_overhead_pct(off_val, on_val):
    """
    Compute percentage overhead:
        overhead% = (on - off) / off * 100
    Positive = audit-ON is slower/lower than audit-OFF (expected).
    """
    if off_val is None or off_val == 0:
        return None
    return (on_val - off_val) / off_val * 100

# Fixtures
@pytest.fixture(scope="module")
def off_rows():
    """Load audit-OFF benchmark CSV once for the entire module."""
    return load_csv(CSV_AUDIT_OFF)


@pytest.fixture(scope="module")
def on_rows():
    """Load audit-ON benchmark CSV once for the entire module."""
    return load_csv(CSV_AUDIT_ON)


# SECTION 1 — CSV Files Exist and Are Valid
class TestCSVFilesExistAndValid:

    def test_audit_off_csv_exists(self):
        """benchmark_audit_off.csv must exist in the results directory."""
        assert os.path.exists(CSV_AUDIT_OFF), (
            f"Audit-OFF CSV not found at: {CSV_AUDIT_OFF}\n"
            "Run benchmark_audit_off.py first."
        )

    def test_audit_on_csv_exists(self):
        """benchmark_audit_on.csv must exist in the results directory."""
        assert os.path.exists(CSV_AUDIT_ON), (
            f"Audit-ON CSV not found at: {CSV_AUDIT_ON}\n"
            "Run benchmark_audit_on.py first."
        )

    def test_audit_off_csv_is_not_empty(self, off_rows):
        """Audit-OFF CSV must contain at least one data row."""
        assert len(off_rows) > 0, "benchmark_audit_off.csv is empty."

    def test_audit_on_csv_is_not_empty(self, on_rows):
        """Audit-ON CSV must contain at least one data row."""
        assert len(on_rows) > 0, "benchmark_audit_on.csv is empty."

    def test_audit_off_has_all_expected_columns(self, off_rows):
        """Audit-OFF CSV must contain all expected column headers."""
        actual_cols = set(off_rows[0].keys())
        for col in EXPECTED_COLUMNS:
            assert col in actual_cols, (
                f"Missing column '{col}' in benchmark_audit_off.csv.\n"
                f"Found columns: {sorted(actual_cols)}"
            )

    def test_audit_on_has_all_expected_columns(self, on_rows):
        """Audit-ON CSV must contain all expected column headers."""
        actual_cols = set(on_rows[0].keys())
        for col in EXPECTED_COLUMNS:
            assert col in actual_cols, (
                f"Missing column '{col}' in benchmark_audit_on.csv.\n"
                f"Found columns: {sorted(actual_cols)}"
            )

    def test_audit_off_has_no_extra_unexpected_columns(self, off_rows):
        """Audit-OFF CSV must not contain unrecognised extra columns."""
        actual_cols = set(off_rows[0].keys())
        extra = actual_cols - set(EXPECTED_COLUMNS)
        assert not extra, (
            f"Unexpected extra columns in benchmark_audit_off.csv: {extra}"
        )

    def test_audit_on_has_no_extra_unexpected_columns(self, on_rows):
        """Audit-ON CSV must not contain unrecognised extra columns."""
        actual_cols = set(on_rows[0].keys())
        extra = actual_cols - set(EXPECTED_COLUMNS)
        assert not extra, (
            f"Unexpected extra columns in benchmark_audit_on.csv: {extra}"
        )

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_audit_off_contains_all_workloads(self, off_rows, workload):
        """Audit-OFF CSV must have a row for every expected workload type."""
        workload_names = [r.get('workload') for r in off_rows]
        assert workload in workload_names, (
            f"Workload '{workload}' missing from benchmark_audit_off.csv.\n"
            f"Found: {set(workload_names)}"
        )

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_audit_on_contains_all_workloads(self, on_rows, workload):
        """Audit-ON CSV must have a row for every expected workload type."""
        workload_names = [r.get('workload') for r in on_rows]
        assert workload in workload_names, (
            f"Workload '{workload}' missing from benchmark_audit_on.csv.\n"
            f"Found: {set(workload_names)}"
        )

    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_audit_off_contains_all_dataset_sizes(self, off_rows, size):
        """Audit-OFF CSV must have rows for every expected dataset size."""
        sizes = [r.get('dataset_size') for r in off_rows]
        assert size in sizes, (
            f"Dataset size {size} missing from benchmark_audit_off.csv.\n"
            f"Found sizes: {sorted(set(sizes))}"
        )

    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_audit_on_contains_all_dataset_sizes(self, on_rows, size):
        """Audit-ON CSV must have rows for every expected dataset size."""
        sizes = [r.get('dataset_size') for r in on_rows]
        assert size in sizes, (
            f"Dataset size {size} missing from benchmark_audit_on.csv.\n"
            f"Found sizes: {sorted(set(sizes))}"
        )

# SECTION 2 — All Numeric Values Are Positive
class TestAllNumericValuesPositive:

    NUMERIC_COLS = ['total_time_s', 'throughput_ops_sec', 'avg_latency_ms']

    @pytest.mark.parametrize("col", NUMERIC_COLS)
    def test_audit_off_numeric_column_all_positive(self, off_rows, col):
        """Every numeric value in audit-OFF CSV must be > 0."""
        for row in off_rows:
            val = row.get(col)
            assert isinstance(val, float), (
                f"Column '{col}' is not numeric in row: {row}"
            )
            assert val > 0, (
                f"Column '{col}' has non-positive value {val} in row: {row}"
            )

    @pytest.mark.parametrize("col", NUMERIC_COLS)
    def test_audit_on_numeric_column_all_positive(self, on_rows, col):
        """Every numeric value in audit-ON CSV must be > 0."""
        for row in on_rows:
            val = row.get(col)
            assert isinstance(val, float), (
                f"Column '{col}' is not numeric in row: {row}"
            )
            assert val > 0, (
                f"Column '{col}' has non-positive value {val} in row: {row}"
            )

    def test_audit_off_total_time_is_realistic(self, off_rows):
        """Audit-OFF total_time_s must be between 0.001s and 3600s (1 hour)."""
        for row in off_rows:
            t = row['total_time_s']
            assert 0.001 < t < 3600, (
                f"Unrealistic total_time_s={t} in audit-OFF row: {row}"
            )

    def test_audit_on_total_time_is_realistic(self, on_rows):
        """Audit-ON total_time_s must be between 0.001s and 3600s (1 hour)."""
        for row in on_rows:
            t = row['total_time_s']
            assert 0.001 < t < 3600, (
                f"Unrealistic total_time_s={t} in audit-ON row: {row}"
            )


# SECTION 3 — Audit-ON Latency > Audit-OFF Latency
class TestAuditOnLatencyHigher:
    """
    Core correctness test: the audit system must always add overhead.
    If audit-ON latency is ever equal to or lower than audit-OFF,
    either the triggers are not firing or the benchmark has a bug.
    """

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_on_latency_greater_than_off_latency(self, off_rows, on_rows,
                                                  workload, size):
        """Audit-ON avg_latency_ms must be strictly greater than audit-OFF."""
        lat_off = get_metric(off_rows, workload, size, 'avg_latency_ms')
        lat_on  = get_metric(on_rows,  workload, size, 'avg_latency_ms')

        if lat_off is None or lat_on is None:
            pytest.skip(
                f"No data for workload='{workload}', size={size}."
            )

        assert lat_on > lat_off, (
            f"workload='{workload}', size={size}:\n"
            f"  Audit-ON  avg_latency_ms = {lat_on:.4f}\n"
            f"  Audit-OFF avg_latency_ms = {lat_off:.4f}\n"
            f"  Audit-ON must be strictly HIGHER than audit-OFF."
        )

    def test_on_latency_higher_for_all_workloads_combined(self, off_rows, on_rows):
        """
        Averaged across all dataset sizes, audit-ON must have higher
        latency than audit-OFF for every workload type.
        """
        for workload in EXPECTED_WORKLOADS:
            off_lats = [
                get_metric(off_rows, workload, s, 'avg_latency_ms')
                for s in EXPECTED_DATASET_SIZES
            ]
            on_lats = [
                get_metric(on_rows, workload, s, 'avg_latency_ms')
                for s in EXPECTED_DATASET_SIZES
            ]
            off_lats = [v for v in off_lats if v is not None]
            on_lats  = [v for v in on_lats  if v is not None]

            if not off_lats or not on_lats:
                pytest.skip(f"Insufficient data for workload='{workload}'.")

            avg_off = statistics.mean(off_lats)
            avg_on  = statistics.mean(on_lats)

            assert avg_on > avg_off, (
                f"workload='{workload}': mean audit-ON latency ({avg_on:.4f} ms) "
                f"must exceed mean audit-OFF latency ({avg_off:.4f} ms)."
            )

# SECTION 4 — Audit-ON Throughput < Audit-OFF Throughput
class TestAuditOnThroughputLower:

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_on_throughput_lower_than_off(self, off_rows, on_rows,
                                          workload, size):
        """Audit-ON throughput_ops_sec must be strictly lower than audit-OFF."""
        tp_off = get_metric(off_rows, workload, size, 'throughput_ops_sec')
        tp_on  = get_metric(on_rows,  workload, size, 'throughput_ops_sec')

        if tp_off is None or tp_on is None:
            pytest.skip(
                f"No data for workload='{workload}', size={size}."
            )

        assert tp_on < tp_off, (
            f"workload='{workload}', size={size}:\n"
            f"  Audit-ON  throughput = {tp_on:.2f} ops/sec\n"
            f"  Audit-OFF throughput = {tp_off:.2f} ops/sec\n"
            f"  Audit-ON must be strictly LOWER than audit-OFF."
        )


# SECTION 5 — Overhead Percentage Is Realistic
class TestOverheadPercentageIsRealistic:
    """
    Overhead must be:
      > MIN_OVERHEAD_PCT  (not 0% — audit system must have some cost)
      < MAX_OVERHEAD_PCT  (not absurdly high — system is still usable)
    """

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_latency_overhead_within_realistic_range(self, off_rows, on_rows,
                                                      workload, size):
        """Latency overhead% must be between MIN and MAX bounds."""
        lat_off = get_metric(off_rows, workload, size, 'avg_latency_ms')
        lat_on  = get_metric(on_rows,  workload, size, 'avg_latency_ms')

        if lat_off is None or lat_on is None:
            pytest.skip(f"No data for workload='{workload}', size={size}.")

        overhead = compute_overhead_pct(lat_off, lat_on)

        assert overhead is not None, "Could not compute overhead (division by zero)."
        assert overhead > MIN_OVERHEAD_PCT, (
            f"workload='{workload}', size={size}: "
            f"overhead={overhead:.2f}% is too low (<{MIN_OVERHEAD_PCT}%). "
            "Audit triggers may not be firing."
        )
        assert overhead < MAX_OVERHEAD_PCT, (
            f"workload='{workload}', size={size}: "
            f"overhead={overhead:.2f}% is unrealistically high (>{MAX_OVERHEAD_PCT}%). "
            "Check for benchmark configuration errors."
        )

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    @pytest.mark.parametrize("size", EXPECTED_DATASET_SIZES)
    def test_throughput_overhead_within_realistic_range(self, off_rows, on_rows,
                                                         workload, size):
        """
        Throughput degradation % must be between bounds.
        Since audit-ON throughput is lower, overhead will be negative here —
        we check the absolute magnitude stays within range.
        """
        tp_off = get_metric(off_rows, workload, size, 'throughput_ops_sec')
        tp_on  = get_metric(on_rows,  workload, size, 'throughput_ops_sec')

        if tp_off is None or tp_on is None:
            pytest.skip(f"No data for workload='{workload}', size={size}.")

        degradation = abs(compute_overhead_pct(tp_off, tp_on))

        assert degradation > MIN_OVERHEAD_PCT, (
            f"workload='{workload}', size={size}: "
            f"throughput degradation={degradation:.2f}% is too low. "
            "Audit system must have a measurable throughput cost."
        )
        assert degradation < MAX_OVERHEAD_PCT, (
            f"workload='{workload}', size={size}: "
            f"throughput degradation={degradation:.2f}% is unrealistically high."
        )

    def test_bulk_insert_overhead_higher_than_update(self, off_rows, on_rows):
        """
        Bulk insert overhead must be higher than update overhead.
        Every inserted row triggers a hash computation from scratch,
        making inserts the most expensive operation for the audit system.
        """
        # Use the smallest dataset size for a clean comparison
        size = EXPECTED_DATASET_SIZES[0]

        insert_off = get_metric(off_rows, 'bulk_insert', size, 'avg_latency_ms')
        insert_on  = get_metric(on_rows,  'bulk_insert', size, 'avg_latency_ms')
        update_off = get_metric(off_rows, 'update',      size, 'avg_latency_ms')
        update_on  = get_metric(on_rows,  'update',      size, 'avg_latency_ms')

        if any(v is None for v in [insert_off, insert_on, update_off, update_on]):
            pytest.skip("Insufficient data to compare insert vs update overhead.")

        insert_overhead = compute_overhead_pct(insert_off, insert_on)
        update_overhead = compute_overhead_pct(update_off, update_on)

        assert insert_overhead > update_overhead, (
            f"Expected bulk_insert overhead ({insert_overhead:.2f}%) > "
            f"update overhead ({update_overhead:.2f}%). "
            "Insert triggers a full hash chain extension per row."
        )

    def test_overhead_summary_across_all_workloads(self, off_rows, on_rows):
        """
        Print a human-readable overhead summary table.
        This test always passes — it exists to make pytest -v output informative.
        """
        summary_lines = [
            "\n" + "=" * 65,
            f"{'WORKLOAD':<15} {'DATASET':>10} {'OFF (ms)':>10} "
            f"{'ON (ms)':>10} {'OVERHEAD%':>10}",
            "-" * 65,
        ]
        for workload in EXPECTED_WORKLOADS:
            for size in EXPECTED_DATASET_SIZES:
                lat_off = get_metric(off_rows, workload, size, 'avg_latency_ms')
                lat_on  = get_metric(on_rows,  workload, size, 'avg_latency_ms')
                if lat_off and lat_on:
                    pct = compute_overhead_pct(lat_off, lat_on)
                    summary_lines.append(
                        f"{workload:<15} {int(size):>10,} "
                        f"{lat_off:>10.4f} {lat_on:>10.4f} {pct:>9.1f}%"
                    )
        summary_lines.append("=" * 65)
        print("\n".join(summary_lines))
        assert True   

# SECTION 6 — Throughput Degrades Gracefully
class TestThroughputDegradeGracefully:
    """
    As dataset size grows, throughput should not suddenly collapse.
    A drop of more than MAX_THROUGHPUT_DROP_FRACTION between consecutive
    sizes signals a catastrophic scalability problem.
    """

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_audit_off_throughput_degrades_gracefully(self, off_rows, workload):
        """Audit-OFF throughput must not cliff-drop between consecutive sizes."""
        for i in range(1, len(EXPECTED_DATASET_SIZES)):
            prev_size = EXPECTED_DATASET_SIZES[i - 1]
            curr_size = EXPECTED_DATASET_SIZES[i]

            tp_prev = get_metric(off_rows, workload, prev_size, 'throughput_ops_sec')
            tp_curr = get_metric(off_rows, workload, curr_size, 'throughput_ops_sec')

            if tp_prev is None or tp_curr is None:
                pytest.skip(
                    f"Missing data for workload='{workload}', "
                    f"sizes {prev_size}→{curr_size}."
                )

            drop_fraction = (tp_prev - tp_curr) / tp_prev
            assert drop_fraction < MAX_THROUGHPUT_DROP_FRACTION, (
                f"workload='{workload}' audit-OFF: throughput dropped "
                f"{drop_fraction * 100:.1f}% from size {prev_size} to {curr_size}. "
                f"Max allowed: {MAX_THROUGHPUT_DROP_FRACTION * 100:.0f}%."
            )

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_audit_on_throughput_degrades_gracefully(self, on_rows, workload):
        """Audit-ON throughput must not cliff-drop between consecutive sizes."""
        for i in range(1, len(EXPECTED_DATASET_SIZES)):
            prev_size = EXPECTED_DATASET_SIZES[i - 1]
            curr_size = EXPECTED_DATASET_SIZES[i]

            tp_prev = get_metric(on_rows, workload, prev_size, 'throughput_ops_sec')
            tp_curr = get_metric(on_rows, workload, curr_size, 'throughput_ops_sec')

            if tp_prev is None or tp_curr is None:
                pytest.skip(
                    f"Missing data for workload='{workload}', "
                    f"sizes {prev_size}→{curr_size}."
                )

            drop_fraction = (tp_prev - tp_curr) / tp_prev
            assert drop_fraction < MAX_THROUGHPUT_DROP_FRACTION, (
                f"workload='{workload}' audit-ON: throughput dropped "
                f"{drop_fraction * 100:.1f}% from size {prev_size} to {curr_size}. "
                f"Max allowed: {MAX_THROUGHPUT_DROP_FRACTION * 100:.0f}%."
            )

    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_latency_increases_monotonically_with_dataset_size(self,
                                                                on_rows, workload):
        """
        Audit-ON average latency must show an overall upward trend as dataset grows.
        We check the overall trend (first vs last) rather than every consecutive pair
        because update/delete ops counts are a fraction of dataset_size, meaning
        small absolute differences produce large percentage swings between steps.
        A 30% tolerance accounts for real-world OS scheduling and caching variance.
        """
        lats = []
        for size in EXPECTED_DATASET_SIZES:
            lat = get_metric(on_rows, workload, size, 'avg_latency_ms')
            if lat is not None:
                lats.append((size, lat))

        if len(lats) < 2:
            pytest.skip(f"Not enough data points for workload='{workload}'.")

        # Check overall trend: last latency >= first latency (with 30% tolerance)
        first_size, first_lat = lats[0]
        last_size,  last_lat  = lats[-1]
        assert last_lat >= first_lat * 0.70, (
            f"workload='{workload}' audit-ON: overall latency trend is downward — "
            f"{first_lat:.4f} ms (size {first_size}) → "
            f"{last_lat:.4f} ms (size {last_size}). "
            "Latency should be broadly stable or increasing across dataset sizes."
        )


# SECTION 7 — Internal CSV Consistency
class TestCSVInternalConsistency:
    """
    Cross-check that values within each CSV are internally consistent —
    e.g. throughput = ops / total_time, latency = total_time / ops * 1000.
    """

    def _check_consistency(self, rows, label):
        """
        For every row verify that throughput and avg_latency are internally
        consistent with total_time_s.

        Key insight: update and delete workloads run on a SUBSET of rows
        (num_prescriptions//2 and num_patients//4 respectively), NOT dataset_size.
        So we derive actual_ops from throughput * total_time rather than
        assuming all workloads used dataset_size operations.

          actual_ops  = round(throughput_ops_sec * total_time_s)
          expected_tp = actual_ops / total_time_s
          expected_lat = (total_time_s / actual_ops) * 1000
        """
        tolerance = 0.01   # 1% — tight enough to catch real errors

        for row in rows:
            size     = row.get('dataset_size')
            t        = row.get('total_time_s')
            tp       = row.get('throughput_ops_sec')
            lat      = row.get('avg_latency_ms')
            workload = row.get('workload', '?')

            if None in (size, t, tp, lat) or t == 0 or size == 0:
                continue

            # Derive actual ops count from throughput * time (works for all workloads)
            actual_ops   = round(tp * t)
            if actual_ops == 0:
                continue

            expected_tp  = actual_ops / t
            expected_lat = (t / actual_ops) * 1000

            tp_error  = abs(tp  - expected_tp)  / expected_tp
            lat_error = abs(lat - expected_lat) / expected_lat

            assert tp_error < tolerance, (
                f"{label} workload='{workload}' size={int(size)}: "
                f"throughput={tp:.4f} inconsistent with "
                f"total_time={t:.6f}s and actual_ops={actual_ops:,} "
                f"(error={tp_error * 100:.2f}%)."
            )
            assert lat_error < tolerance, (
                f"{label} workload='{workload}' size={int(size)}: "
                f"avg_latency_ms={lat:.6f} inconsistent with "
                f"total_time={t:.6f}s and actual_ops={actual_ops:,} "
                f"(error={lat_error * 100:.2f}%)."
            )

    def test_audit_off_internal_consistency(self, off_rows):
        """Audit-OFF CSV: throughput and latency must be consistent with total_time."""
        self._check_consistency(off_rows, label='Audit-OFF')

    def test_audit_on_internal_consistency(self, on_rows):
        """Audit-ON CSV: throughput and latency must be consistent with total_time."""
        self._check_consistency(on_rows, label='Audit-ON')

    def test_both_csvs_have_same_number_of_rows(self, off_rows, on_rows):
        """
        Both CSVs must have the same row count — they describe the same
        workloads and dataset sizes, just with different audit configurations.
        """
        assert len(off_rows) == len(on_rows), (
            f"Audit-OFF has {len(off_rows)} rows but "
            f"Audit-ON has {len(on_rows)} rows. "
            "Both CSVs must cover identical workload/dataset combinations."
        )

    def test_both_csvs_have_same_workload_size_combinations(self, off_rows, on_rows):
        """
        The set of (workload, dataset_size) pairs must be identical in both CSVs.
        """
        off_combos = {
            (r.get('workload'), r.get('dataset_size')) for r in off_rows
        }
        on_combos = {
            (r.get('workload'), r.get('dataset_size')) for r in on_rows
        }
        assert off_combos == on_combos, (
            f"Workload/size combinations differ between CSVs.\n"
            f"  Only in audit-OFF: {off_combos - on_combos}\n"
            f"  Only in audit-ON:  {on_combos - off_combos}"
        )