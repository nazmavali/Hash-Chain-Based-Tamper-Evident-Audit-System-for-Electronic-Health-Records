"""
Test File 6 — Step 9: analyze_results.py validation

Covers:
  - load_csv() correctly parses both CSVs into keyed dicts
  - compute_overhead() produces correct overhead % values
  - compute_overhead() produces correct throughput drop % values
  - All overhead values are positive (audit-ON always costs more)
  - Summary CSV is saved with all required columns and rows
  - All three chart PNG files are created and non-empty
  - Key findings are present in the data (bulk_insert highest overhead,
    overhead grows with dataset size, update lowest overhead)
"""

import pytest
import os
import csv
import sys

# Make analyze_results importable from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from analyze_results import (
    load_csv,
    compute_overhead,
    save_summary_csv,
    chart_latency_overhead,
    chart_throughput_comparison,
    chart_overhead_pct,
    CSV_OFF, CSV_ON, CSV_SUMMARY,
    CHART_LATENCY, CHART_TP, CHART_OH_PCT,
    WORKLOADS, RESULTS_DIR,
)

# Expected values derived from real CSVs
EXPECTED_SIZES    = [60000, 120000, 180000, 300000]
EXPECTED_WORKLOADS = ['bulk_insert', 'update', 'delete']

# Tolerance for floating point comparisons
TOLERANCE = 0.5   # 0.5% tolerance on overhead calculations

# Fixtures
@pytest.fixture(scope="module")
def off_data():
    """Load audit-OFF CSV once for the module."""
    if not os.path.exists(CSV_OFF):
        pytest.skip(f"CSV not found: {CSV_OFF}. Run benchmark scripts first.")
    return load_csv(CSV_OFF)


@pytest.fixture(scope="module")
def on_data():
    """Load audit-ON CSV once for the module."""
    if not os.path.exists(CSV_ON):
        pytest.skip(f"CSV not found: {CSV_ON}. Run benchmark scripts first.")
    return load_csv(CSV_ON)


@pytest.fixture(scope="module")
def summary_rows(off_data, on_data):
    """Compute overhead summary rows once for the module."""
    return compute_overhead(off_data, on_data)


@pytest.fixture(scope="module")
def summary_dict(summary_rows):
    """Index summary rows by (dataset_size, workload) for easy lookup."""
    return {(r['dataset_size'], r['workload']): r for r in summary_rows}

# Helper
def approx_equal(actual, expected, tolerance_pct=TOLERANCE):
    """Check two values are within tolerance_pct % of each other."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / abs(expected) * 100 <= tolerance_pct

# SECTION 1 — load_csv()
class TestLoadCSV:

    def test_load_csv_returns_dict(self, off_data):
        """load_csv must return a dict."""
        assert isinstance(off_data, dict), "load_csv must return a dict."

    def test_load_csv_has_correct_number_of_keys(self, off_data):
        """Audit-OFF CSV has 4 sizes × 3 workloads = 12 entries."""
        assert len(off_data) == 12, (
            f"Expected 12 entries in off_data, got {len(off_data)}."
        )

    def test_load_csv_keys_are_tuples(self, off_data):
        """Keys must be (int, str) tuples."""
        for key in off_data:
            assert isinstance(key, tuple) and len(key) == 2
            assert isinstance(key[0], int)
            assert isinstance(key[1], str)

    @pytest.mark.parametrize("size", EXPECTED_SIZES)
    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_load_csv_all_expected_keys_present(self, off_data, size, workload):
        """Every (size, workload) combination must be present."""
        assert (size, workload) in off_data, (
            f"Key ({size}, '{workload}') missing from off_data."
        )

    def test_load_csv_values_have_required_fields(self, off_data):
        """Each value dict must have all three metric fields."""
        for key, val in off_data.items():
            for field in ['total_time_s', 'throughput_ops_sec', 'avg_latency_ms']:
                assert field in val, (
                    f"Field '{field}' missing for key {key}."
                )
                assert isinstance(val[field], float), (
                    f"Field '{field}' for key {key} must be a float."
                )

    def test_load_csv_all_values_positive(self, off_data, on_data):
        """All metric values in both CSVs must be positive."""
        for data, label in [(off_data, 'OFF'), (on_data, 'ON')]:
            for key, val in data.items():
                for field, v in val.items():
                    assert v > 0, (
                        f"Audit-{label} key {key} field '{field}' is non-positive: {v}"
                    )

    def test_load_csv_known_value_bulk_insert_60k_off(self, off_data):
        """Spot-check: audit-OFF bulk_insert at 60k latency = 0.007084 ms."""
        val = off_data.get((60000, 'bulk_insert'))
        assert val is not None
        assert approx_equal(val['avg_latency_ms'], 0.007084), (
            f"Expected ~0.007084 ms, got {val['avg_latency_ms']}"
        )

    def test_load_csv_known_value_bulk_insert_60k_on(self, on_data):
        """Spot-check: audit-ON bulk_insert at 60k latency = 0.035246 ms."""
        val = on_data.get((60000, 'bulk_insert'))
        assert val is not None
        assert approx_equal(val['avg_latency_ms'], 0.035246), (
            f"Expected ~0.035246 ms, got {val['avg_latency_ms']}"
        )

# SECTION 2 — compute_overhead() correctness
class TestComputeOverhead:

    def test_returns_list(self, summary_rows):
        """compute_overhead must return a list."""
        assert isinstance(summary_rows, list)

    def test_returns_12_rows(self, summary_rows):
        """Must return 4 sizes × 3 workloads = 12 rows."""
        assert len(summary_rows) == 12, (
            f"Expected 12 summary rows, got {len(summary_rows)}."
        )

    def test_each_row_has_all_fields(self, summary_rows):
        """Every summary row must have all 8 required fields."""
        required = [
            'dataset_size', 'workload',
            'off_latency_ms', 'on_latency_ms', 'latency_overhead_pct',
            'off_throughput', 'on_throughput', 'throughput_drop_pct',
        ]
        for row in summary_rows:
            for field in required:
                assert field in row, (
                    f"Field '{field}' missing in summary row: {row}"
                )

    # Spot-check exact overhead values
    def test_bulk_insert_60k_latency_overhead(self, summary_dict):
        """bulk_insert at 60k: overhead = (0.035246-0.007084)/0.007084*100 ≈ 397.5%"""
        row = summary_dict.get((60000, 'bulk_insert'))
        assert row is not None
        assert approx_equal(row['latency_overhead_pct'], 397.5), (
            f"Expected ~397.5%, got {row['latency_overhead_pct']}%"
        )

    def test_update_60k_latency_overhead(self, summary_dict):
        """update at 60k: overhead ≈ 12.6%"""
        row = summary_dict.get((60000, 'update'))
        assert row is not None
        assert approx_equal(row['latency_overhead_pct'], 12.6), (
            f"Expected ~12.6%, got {row['latency_overhead_pct']}%"
        )

    def test_delete_60k_latency_overhead(self, summary_dict):
        """delete at 60k: overhead ≈ 81.3%"""
        row = summary_dict.get((60000, 'delete'))
        assert row is not None
        assert approx_equal(row['latency_overhead_pct'], 81.3), (
            f"Expected ~81.3%, got {row['latency_overhead_pct']}%"
        )

    def test_bulk_insert_300k_latency_overhead(self, summary_dict):
        """bulk_insert at 300k: overhead ≈ 744.1% (highest overhead point)"""
        row = summary_dict.get((300000, 'bulk_insert'))
        assert row is not None
        assert approx_equal(row['latency_overhead_pct'], 744.1), (
            f"Expected ~744.1%, got {row['latency_overhead_pct']}%"
        )

    def test_bulk_insert_60k_throughput_drop(self, summary_dict):
        """bulk_insert at 60k: throughput drop ≈ 79.9%"""
        row = summary_dict.get((60000, 'bulk_insert'))
        assert row is not None
        assert approx_equal(row['throughput_drop_pct'], 79.9), (
            f"Expected ~79.9%, got {row['throughput_drop_pct']}%"
        )

    def test_overhead_formula_is_correct(self, summary_rows):
        """
        Verify formula: latency_overhead_pct = (on-off)/off*100
        for every row independently.
        """
        for row in summary_rows:
            expected = (
                (row['on_latency_ms'] - row['off_latency_ms'])
                / row['off_latency_ms'] * 100
            )
            assert approx_equal(row['latency_overhead_pct'], expected, 0.1), (
                f"Overhead formula wrong for "
                f"({row['dataset_size']}, {row['workload']}): "
                f"expected {expected:.2f}%, got {row['latency_overhead_pct']}%"
            )

    def test_throughput_drop_formula_is_correct(self, summary_rows):
        """
        Verify formula: throughput_drop_pct = (off-on)/off*100
        for every row independently.
        """
        for row in summary_rows:
            expected = (
                (row['off_throughput'] - row['on_throughput'])
                / row['off_throughput'] * 100
            )
            assert approx_equal(row['throughput_drop_pct'], expected, 0.1), (
                f"TP drop formula wrong for "
                f"({row['dataset_size']}, {row['workload']}): "
                f"expected {expected:.2f}%, got {row['throughput_drop_pct']}%"
            )

# SECTION 3 — All Overheads Are Positive
class TestOverheadsArePositive:

    @pytest.mark.parametrize("size", EXPECTED_SIZES)
    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_latency_overhead_is_positive(self, summary_dict, size, workload):
        """Audit-ON latency must always be higher than audit-OFF."""
        row = summary_dict.get((size, workload))
        if row is None:
            pytest.skip(f"No data for ({size}, {workload})")
        assert row['latency_overhead_pct'] > 0, (
            f"({size}, {workload}): overhead={row['latency_overhead_pct']}% "
            "must be positive."
        )

    @pytest.mark.parametrize("size", EXPECTED_SIZES)
    @pytest.mark.parametrize("workload", EXPECTED_WORKLOADS)
    def test_throughput_drop_is_positive(self, summary_dict, size, workload):
        """Audit-ON throughput must always be lower than audit-OFF."""
        row = summary_dict.get((size, workload))
        if row is None:
            pytest.skip(f"No data for ({size}, {workload})")
        assert row['throughput_drop_pct'] > 0, (
            f"({size}, {workload}): tp_drop={row['throughput_drop_pct']}% "
            "must be positive."
        )

    def test_on_latency_always_greater_than_off(self, summary_rows):
        """For every row: on_latency_ms > off_latency_ms."""
        for row in summary_rows:
            assert row['on_latency_ms'] > row['off_latency_ms'], (
                f"({row['dataset_size']}, {row['workload']}): "
                f"ON latency {row['on_latency_ms']} <= OFF latency {row['off_latency_ms']}"
            )

    def test_on_throughput_always_less_than_off(self, summary_rows):
        """For every row: on_throughput < off_throughput."""
        for row in summary_rows:
            assert row['on_throughput'] < row['off_throughput'], (
                f"({row['dataset_size']}, {row['workload']}): "
                f"ON throughput {row['on_throughput']} >= OFF throughput {row['off_throughput']}"
            )

# SECTION 4 — Key Research Findings
class TestKeyFindings:

    def test_bulk_insert_has_highest_overhead_at_every_size(self, summary_dict):
        """
        Finding 1: bulk_insert must have higher overhead than update and delete
        at every dataset size — because every insert triggers a full hash
        chain extension per row.
        """
        for size in EXPECTED_SIZES:
            insert_oh = summary_dict[(size, 'bulk_insert')]['latency_overhead_pct']
            update_oh = summary_dict[(size, 'update')]['latency_overhead_pct']
            delete_oh = summary_dict[(size, 'delete')]['latency_overhead_pct']
            assert insert_oh > update_oh, (
                f"Size {size}: bulk_insert overhead ({insert_oh:.1f}%) must be "
                f"> update overhead ({update_oh:.1f}%)."
            )
            assert insert_oh > delete_oh, (
                f"Size {size}: bulk_insert overhead ({insert_oh:.1f}%) must be "
                f"> delete overhead ({delete_oh:.1f}%)."
            )

    def test_bulk_insert_overhead_grows_with_dataset_size(self, summary_dict):
        """
        Finding 2: bulk_insert overhead must be higher at 300k than at 60k —
        proving the audit system cost scales with audit_log size.
        """
        oh_60k  = summary_dict[(60000,  'bulk_insert')]['latency_overhead_pct']
        oh_300k = summary_dict[(300000, 'bulk_insert')]['latency_overhead_pct']
        assert oh_300k > oh_60k, (
            f"bulk_insert overhead must grow with dataset size: "
            f"60k={oh_60k:.1f}% → 300k={oh_300k:.1f}%"
        )

    def test_update_has_lowest_overhead_at_every_size(self, summary_dict):
        """
        Finding 3: update must have lower overhead than delete at every size —
        update overhead is the most manageable workload.
        """
        for size in EXPECTED_SIZES:
            update_oh = summary_dict[(size, 'update')]['latency_overhead_pct']
            delete_oh = summary_dict[(size, 'delete')]['latency_overhead_pct']
            assert update_oh < delete_oh, (
                f"Size {size}: update overhead ({update_oh:.1f}%) must be "
                f"< delete overhead ({delete_oh:.1f}%)."
            )

    def test_overhead_range_is_realistic(self, summary_rows):
        """
        All overhead values must be between 1% and 2000% —
        within the realistic bounds defined in the benchmark test.
        """
        for row in summary_rows:
            oh = row['latency_overhead_pct']
            assert 1.0 < oh < 2000.0, (
                f"({row['dataset_size']}, {row['workload']}): "
                f"overhead {oh:.1f}% is outside realistic range [1%, 2000%]."
            )

    def test_delete_300k_overhead_greater_than_60k(self, summary_dict):
        """Delete overhead must also grow from 60k to 300k."""
        oh_60k  = summary_dict[(60000,  'delete')]['latency_overhead_pct']
        oh_300k = summary_dict[(300000, 'delete')]['latency_overhead_pct']
        assert oh_300k > oh_60k, (
            f"Delete overhead should grow: 60k={oh_60k:.1f}% → 300k={oh_300k:.1f}%"
        )

# SECTION 5 — Summary CSV Output
class TestSummaryCSVOutput:

    @pytest.fixture(autouse=True, scope="class")
    def generate_summary_csv(self, summary_rows):
        """Generate the summary CSV before any test in this class runs."""
        os.makedirs(RESULTS_DIR, exist_ok=True)
        save_summary_csv(summary_rows)

    def test_summary_csv_exists(self):
        """overhead_summary_table.csv must be created."""
        assert os.path.exists(CSV_SUMMARY), (
            f"Summary CSV not found at: {CSV_SUMMARY}"
        )

    def test_summary_csv_is_not_empty(self):
        """Summary CSV must not be empty."""
        assert os.path.getsize(CSV_SUMMARY) > 0

    def test_summary_csv_has_correct_columns(self):
        """Summary CSV must contain all 8 expected columns."""
        expected_cols = [
            'dataset_size', 'workload',
            'off_latency_ms', 'on_latency_ms', 'latency_overhead_pct',
            'off_throughput', 'on_throughput', 'throughput_drop_pct',
        ]
        with open(CSV_SUMMARY, newline='') as f:
            reader = csv.DictReader(f)
            actual_cols = reader.fieldnames
        for col in expected_cols:
            assert col in actual_cols, (
                f"Column '{col}' missing from summary CSV."
            )

    def test_summary_csv_has_12_data_rows(self):
        """Summary CSV must have 12 data rows (4 sizes × 3 workloads)."""
        with open(CSV_SUMMARY, newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 12, (
            f"Expected 12 data rows in summary CSV, got {len(rows)}."
        )

    def test_summary_csv_values_are_numeric(self):
        """All metric columns in the summary CSV must be parseable as float."""
        numeric_cols = [
            'off_latency_ms', 'on_latency_ms', 'latency_overhead_pct',
            'off_throughput', 'on_throughput', 'throughput_drop_pct',
        ]
        with open(CSV_SUMMARY, newline='') as f:
            for row in csv.DictReader(f):
                for col in numeric_cols:
                    try:
                        float(row[col])
                    except ValueError:
                        pytest.fail(
                            f"Column '{col}' value '{row[col]}' is not numeric."
                        )

# SECTION 6 — Chart Files Are Created
class TestChartFilesCreated:

    @pytest.fixture(autouse=True, scope="class")
    def generate_all_charts(self, summary_rows):
        """Generate all three charts before tests in this class run."""
        os.makedirs(RESULTS_DIR, exist_ok=True)
        chart_latency_overhead(summary_rows)
        chart_throughput_comparison(summary_rows)
        chart_overhead_pct(summary_rows)

    @pytest.mark.parametrize("chart_path,chart_name", [
        (CHART_LATENCY, 'chart_latency_overhead.png'),
        (CHART_TP,      'chart_throughput_comparison.png'),
        (CHART_OH_PCT,  'chart_overhead_pct.png'),
    ])
    def test_chart_file_exists(self, chart_path, chart_name):
        """Each chart PNG must exist after generation."""
        assert os.path.exists(chart_path), (
            f"Chart not found: {chart_name}"
        )

    @pytest.mark.parametrize("chart_path,chart_name", [
        (CHART_LATENCY, 'chart_latency_overhead.png'),
        (CHART_TP,      'chart_throughput_comparison.png'),
        (CHART_OH_PCT,  'chart_overhead_pct.png'),
    ])
    def test_chart_file_is_not_empty(self, chart_path, chart_name):
        """Each chart PNG must have a non-zero file size."""
        size = os.path.getsize(chart_path)
        assert size > 0, f"{chart_name} exists but is empty."

    @pytest.mark.parametrize("chart_path,chart_name", [
        (CHART_LATENCY, 'chart_latency_overhead.png'),
        (CHART_TP,      'chart_throughput_comparison.png'),
        (CHART_OH_PCT,  'chart_overhead_pct.png'),
    ])
    def test_chart_file_is_valid_png(self, chart_path, chart_name):
        """Each chart must start with the PNG magic bytes (\\x89PNG)."""
        with open(chart_path, 'rb') as f:
            header = f.read(4)
        assert header == b'\x89PNG', (
            f"{chart_name} does not appear to be a valid PNG file."
        )

    @pytest.mark.parametrize("chart_path,chart_name", [
        (CHART_LATENCY, 'chart_latency_overhead.png'),
        (CHART_TP,      'chart_throughput_comparison.png'),
        (CHART_OH_PCT,  'chart_overhead_pct.png'),
    ])
    def test_chart_file_is_reasonably_sized(self, chart_path, chart_name):
        """Each chart PNG must be at least 50KB — too small means blank/corrupt."""
        size_kb = os.path.getsize(chart_path) / 1024
        assert size_kb > 50, (
            f"{chart_name} is only {size_kb:.1f}KB — "
            "expected at least 50KB for a proper chart."
        )