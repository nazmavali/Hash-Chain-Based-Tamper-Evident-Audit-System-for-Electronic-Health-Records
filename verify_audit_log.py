import psycopg2
import hashlib
import sys

DB_PARAMS = {
    'host': 'localhost',
    'database': 'healthcare_db',
    'user': 'postgres',
    'password': '36375213',
    'port': '5432'
}

GENESIS_HASH = hashlib.sha256(b'GENESIS').hexdigest()


def compute_hash(old_value, new_value, table_name, record_id, operation, previous_hash):
    data = (
        (old_value or '') +
        (new_value or '') +
        table_name +
        str(record_id) +
        operation +
        previous_hash
    )
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def verify_audit_log():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
    except Exception as e:
        print(f"Database connection failed: {e}")
        sys.exit(1)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            log_id,
            table_name,
            record_id,
            operation,
            old_value::text,
            new_value::text,
            previous_hash,
            current_hash
        FROM audit_log
        ORDER BY log_id ASC;
    """)

    rows = cursor.fetchall()

    if not rows:
        print("Audit log is empty. Nothing to verify.")
        return

    expected_previous_hash = GENESIS_HASH

    for row in rows:
        (
            log_id,
            table_name,
            record_id,
            operation,
            old_value,
            new_value,
            stored_previous_hash,
            stored_current_hash
        ) = row

        if stored_previous_hash != expected_previous_hash:
            print(f"[TAMPER DETECTED] at log_id {log_id}")
            print("Reason: previous_hash does not match expected hash")
            return

        computed_hash = compute_hash(
            old_value,
            new_value,
            table_name,
            record_id,
            operation,
            stored_previous_hash
        )

        if computed_hash != stored_current_hash:
            print(f"[TAMPER DETECTED] at log_id {log_id}")
            print("Reason: current_hash mismatch")
            return

        expected_previous_hash = stored_current_hash

    print("Audit log verification PASSED. No tampering detected.")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    verify_audit_log()
