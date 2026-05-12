import psycopg2
import time
import sys
import os
import csv

DB_PARAMS = {
    'host': 'localhost',
    'database': 'healthcare_db',
    'user': 'postgres',
    'password': '36375213',
    'port': '5432'
}

# dataset_size key = num_patients + num_prescriptions (total ops for throughput)
dataset_sizes = [
    (10000, 50000),    # total = 60000
    (20000, 100000),   # total = 120000
    (30000, 150000),   # total = 180000
    (50000, 250000),   # total = 300000
]

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
OUTPUT_CSV  = os.path.join(RESULTS_DIR, 'benchmark_audit_off.csv')


def connect_db():
    try:
        return psycopg2.connect(**DB_PARAMS)
    except Exception as e:
        print(f"Database connection failed: {e}")
        sys.exit(1)


def clear_tables(conn):
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE audit_log      RESTART IDENTITY;")
    cur.execute("TRUNCATE TABLE prescriptions  RESTART IDENTITY CASCADE;")
    cur.execute("TRUNCATE TABLE patients       RESTART IDENTITY CASCADE;")
    conn.commit()
    cur.close()


def disable_triggers(conn):
    cur = conn.cursor()
    cur.execute("ALTER TABLE patients      DISABLE TRIGGER patients_audit_trigger;")
    cur.execute("ALTER TABLE prescriptions DISABLE TRIGGER prescriptions_audit_trigger;")
    conn.commit()
    cur.close()


def enable_triggers(conn):
    cur = conn.cursor()
    cur.execute("ALTER TABLE patients      ENABLE TRIGGER patients_audit_trigger;")
    cur.execute("ALTER TABLE prescriptions ENABLE TRIGGER prescriptions_audit_trigger;")
    conn.commit()
    cur.close()


def bulk_insert(conn, num_patients, num_prescriptions):
    cur = conn.cursor()
    patient_vals = ",".join(
        ["('John', 'Doe', '1980-01-01', 'M')"] * num_patients
    )
    cur.execute(
        f"INSERT INTO patients (first_name, last_name, date_of_birth, gender) "
        f"VALUES {patient_vals};"
    )
    presc_vals = ",".join(
        [f"({i}, 'Lisinopril', '10mg', 'Once daily', '2020-01-01', "
         f"NULL, 0, 'Active', 'Take with food')"
         for i in range(1, num_patients + 1)]
    )
    cur.execute(
        f"INSERT INTO prescriptions "
        f"(patient_id, medication_name, dosage, frequency, prescribed_date, "
        f"end_date, refills_left, status, instructions) VALUES {presc_vals};"
    )
    conn.commit()
    cur.close()


def update_workload(conn, num_updates):
    cur = conn.cursor()
    for i in range(1, num_updates + 1):
        cur.execute(
            "UPDATE prescriptions SET status = 'Completed' WHERE id = %s;", (i,)
        )
    conn.commit()
    cur.close()


def delete_workload(conn, num_deletes):
    cur = conn.cursor()
    for i in range(1, num_deletes + 1):
        cur.execute("DELETE FROM patients WHERE id = %s;", (i,))
    conn.commit()
    cur.close()


def run_benchmark():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    results = []

    for num_patients, num_prescriptions in dataset_sizes:
        total_ops  = num_patients + num_prescriptions
        num_updates = num_prescriptions // 2
        num_deletes = num_patients // 4

        print(f"\nDataset: {num_patients:,} patients + "
              f"{num_prescriptions:,} prescriptions  (total={total_ops:,})")

        conn = connect_db()
        disable_triggers(conn)
        clear_tables(conn)

        # Bulk Insert
        t0 = time.perf_counter()
        bulk_insert(conn, num_patients, num_prescriptions)
        t1 = time.perf_counter()
        elapsed    = t1 - t0
        throughput = total_ops / elapsed
        latency_ms = elapsed / total_ops * 1000
        print(f"  bulk_insert  : {elapsed:.3f}s | "
              f"{throughput:,.1f} ops/s | {latency_ms:.6f} ms/op")
        results.append({
            'dataset_size':       total_ops,
            'workload':           'bulk_insert',
            'total_time_s':       round(elapsed, 6),
            'throughput_ops_sec': round(throughput, 4),
            'avg_latency_ms':     round(latency_ms, 6),
        })

        # Update Workload
        t0 = time.perf_counter()
        update_workload(conn, num_updates)
        t1 = time.perf_counter()
        elapsed    = t1 - t0
        throughput = num_updates / elapsed
        latency_ms = elapsed / num_updates * 1000
        print(f"  update       : {elapsed:.3f}s | "
              f"{throughput:,.1f} ops/s | {latency_ms:.6f} ms/op")
        results.append({
            'dataset_size':       total_ops,
            'workload':           'update',
            'total_time_s':       round(elapsed, 6),
            'throughput_ops_sec': round(throughput, 4),
            'avg_latency_ms':     round(latency_ms, 6),
        })

        # Delete Workload
        t0 = time.perf_counter()
        delete_workload(conn, num_deletes)
        t1 = time.perf_counter()
        elapsed    = t1 - t0
        throughput = num_deletes / elapsed
        latency_ms = elapsed / num_deletes * 1000
        print(f"  delete       : {elapsed:.3f}s | "
              f"{throughput:,.1f} ops/s | {latency_ms:.6f} ms/op")
        results.append({
            'dataset_size':       total_ops,
            'workload':           'delete',
            'total_time_s':       round(elapsed, 6),
            'throughput_ops_sec': round(throughput, 4),
            'avg_latency_ms':     round(latency_ms, 6),
        })

        enable_triggers(conn)
        conn.close()

    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'dataset_size', 'workload',
            'total_time_s', 'throughput_ops_sec', 'avg_latency_ms'
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    run_benchmark()