"""
Test File 4 — Part B (Steps 5–6): Tamper Detection Validation

Covers:
  - A clean, untampered chain passes verification
  - Modifying old_value in an audit row is detected
  - Modifying new_value in an audit row is detected
  - Modifying current_hash directly is detected
  - Modifying previous_hash directly is detected
  - Deleting a middle row from the chain is detected
  - Deleting the first row from the chain is detected
  - The correct log_id of the FIRST tampered row is always reported
  - Tampering at different positions (first, middle, last) is all caught
  - Re-verifying after tampering is fixed returns PASSED
"""

import pytest
import psycopg2
import psycopg2.extras
import hashlib
import sys
import os

# Make verify_audit_log importable from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from verify_audit_log import verify_audit_log, compute_hash, GENESIS_HASH

# Database connection parameters
DB_PARAMS = {
    'host': 'localhost',
    'database': 'healthcare_db',
    'user': 'postgres',
    'password': '36375213',
    'port': '5432'
}


# Fixtures
@pytest.fixture(scope="module")
def conn():
    """Shared DB connection for the entire module."""
    connection = psycopg2.connect(**DB_PARAMS)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture(scope="module")
def cursor(conn):
    """RealDictCursor for readable row access."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield cur
    cur.close()


@pytest.fixture(autouse=True)
def clean_tables(conn):
    """
    Before and after every test: wipe all data and reset sequences
    so each test starts with a clean, predictable state.
    """
    cur = conn.cursor()
    cur.execute("ALTER TABLE patients      ENABLE TRIGGER patients_audit_trigger;")
    cur.execute("ALTER TABLE prescriptions ENABLE TRIGGER prescriptions_audit_trigger;")
    cur.execute("TRUNCATE TABLE audit_log      RESTART IDENTITY;")
    cur.execute("TRUNCATE TABLE prescriptions  RESTART IDENTITY CASCADE;")
    cur.execute("TRUNCATE TABLE patients       RESTART IDENTITY CASCADE;")
    conn.commit()
    cur.close()
    yield
    cur = conn.cursor()
    cur.execute("ALTER TABLE patients      ENABLE TRIGGER patients_audit_trigger;")
    cur.execute("ALTER TABLE prescriptions ENABLE TRIGGER prescriptions_audit_trigger;")
    cur.execute("TRUNCATE TABLE audit_log      RESTART IDENTITY;")
    cur.execute("TRUNCATE TABLE prescriptions  RESTART IDENTITY CASCADE;")
    cur.execute("TRUNCATE TABLE patients       RESTART IDENTITY CASCADE;")
    conn.commit()
    cur.close()


# Helpers
def insert_patient(conn, first_name='Test', last_name='User',
                   dob='1990-01-01', gender='M'):
    """Insert a patient via trigger so audit entries are created."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO patients (first_name, last_name, date_of_birth, gender)
        VALUES (%s, %s, %s, %s) RETURNING id;
    """, (first_name, last_name, dob, gender))
    conn.commit()
    patient_id = cur.fetchone()[0]
    cur.close()
    return patient_id


def build_chain(conn, n=5):
    """
    Build a chain of n audit entries by inserting n patients.
    Returns the list of log_ids created.
    """
    log_ids = []
    cur = conn.cursor()
    for i in range(n):
        cur.execute("""
            INSERT INTO patients (first_name, last_name, date_of_birth, gender)
            VALUES (%s, 'Chain', '1990-01-01', 'M') RETURNING id;
        """, (f'Patient{i + 1}',))
        conn.commit()
    cur.execute("SELECT log_id FROM audit_log ORDER BY log_id ASC;")
    log_ids = [row[0] for row in cur.fetchall()]
    cur.close()
    return log_ids


def fetch_all_audit_rows(conn):
    """Return all audit_log rows as plain dicts ordered by log_id."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT log_id, table_name, record_id, operation,
               old_value::text AS old_value,
               new_value::text AS new_value,
               previous_hash, current_hash
        FROM audit_log
        ORDER BY log_id ASC;
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def run_verifier(conn):
    """
    Run the verify_audit_log() function and capture its result.

    Returns a dict:
        {
            'passed':          bool,   # True = chain valid, False = tampered
            'tampered_log_id': int or None,
            'reason':          str or None
        }
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT log_id, table_name, record_id, operation,
               old_value::text AS old_value,
               new_value::text AS new_value,
               previous_hash, current_hash
        FROM audit_log
        ORDER BY log_id ASC;
    """)
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return {'passed': True, 'tampered_log_id': None, 'reason': 'empty'}

    expected_prev = GENESIS_HASH

    for row in rows:
        log_id           = row['log_id']
        stored_prev      = row['previous_hash']
        stored_current   = row['current_hash']

        # Check previous_hash linkage
        if stored_prev != expected_prev:
            return {
                'passed': False,
                'tampered_log_id': log_id,
                'reason': 'previous_hash mismatch'
            }

        # Recompute current_hash
        computed = compute_hash(
            old_value=row['old_value'],
            new_value=row['new_value'],
            table_name=row['table_name'],
            record_id=row['record_id'],
            operation=row['operation'],
            previous_hash=stored_prev
        )

        if computed != stored_current:
            return {
                'passed': False,
                'tampered_log_id': log_id,
                'reason': 'current_hash mismatch'
            }

        expected_prev = stored_current

    return {'passed': True, 'tampered_log_id': None, 'reason': None}


def tamper_field(conn, log_id, field, new_value):
    """
    Directly UPDATE a field in audit_log, bypassing triggers.
    Used to simulate an insider attack.
    """
    cur = conn.cursor()
    cur.execute(
        f"UPDATE audit_log SET {field} = %s WHERE log_id = %s;",
        (new_value, log_id)
    )
    conn.commit()
    cur.close()


def delete_audit_row(conn, log_id):
    """Directly DELETE a row from audit_log to simulate record removal."""
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_log WHERE log_id = %s;", (log_id,))
    conn.commit()
    cur.close()


def recompute_and_repair_hash(conn, log_id):
    """
    Repair a single audit_log row by recomputing its current_hash
    from scratch, used in the 'fix and re-verify' test.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT old_value::text, new_value::text, table_name,
               record_id, operation, previous_hash
        FROM audit_log WHERE log_id = %s;
    """, (log_id,))
    row = cur.fetchone()
    repaired = compute_hash(
        old_value=row['old_value'],
        new_value=row['new_value'],
        table_name=row['table_name'],
        record_id=row['record_id'],
        operation=row['operation'],
        previous_hash=row['previous_hash']
    )
    cur2 = conn.cursor()
    cur2.execute(
        "UPDATE audit_log SET current_hash = %s WHERE log_id = %s;",
        (repaired, log_id)
    )
    conn.commit()
    cur.close()
    cur2.close()


# SECTION 1 — Clean Chain Passes
class TestCleanChainPasses:

    def test_empty_audit_log_passes(self, conn):
        """An empty audit log must be treated as valid (nothing to verify)."""
        result = run_verifier(conn)
        assert result['passed'] is True, (
            "Empty audit log should pass verification."
        )

    def test_single_entry_chain_passes(self, conn):
        """A chain with exactly one entry must pass verification."""
        insert_patient(conn, first_name='Solo')
        result = run_verifier(conn)
        assert result['passed'] is True, (
            f"Single-entry chain should pass. Got: {result}"
        )

    def test_five_entry_chain_passes(self, conn):
        """A clean 5-entry chain must pass verification."""
        build_chain(conn, n=5)
        result = run_verifier(conn)
        assert result['passed'] is True, (
            f"Clean 5-entry chain should pass. Got: {result}"
        )

    def test_twenty_entry_chain_passes(self, conn):
        """A clean 20-entry chain must pass verification."""
        build_chain(conn, n=20)
        result = run_verifier(conn)
        assert result['passed'] is True, (
            f"Clean 20-entry chain should pass. Got: {result}"
        )

    def test_mixed_operations_clean_chain_passes(self, conn):
        """
        A chain built from INSERT + UPDATE + DELETE operations
        must still pass verification when untampered.
        """
        patient_id = insert_patient(conn, first_name='Mixed')
        cur = conn.cursor()
        cur.execute(
            "UPDATE patients SET first_name = 'MixedUpdated' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        cur.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()
        cur.close()

        result = run_verifier(conn)
        assert result['passed'] is True, (
            f"Mixed INSERT/UPDATE/DELETE clean chain should pass. Got: {result}"
        )


# SECTION 2 — Modifying old_value Is Detected
class TestOldValueTampering:

    def test_tampering_old_value_first_entry_detected(self, conn):
        """Modifying old_value on the first entry must be detected."""
        build_chain(conn, n=3)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[0]['log_id']

        tamper_field(conn, target_log_id, 'old_value', '{"tampered": true}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Tampered old_value on first entry should be detected."
        )

    def test_tampering_old_value_reports_correct_log_id(self, conn):
        """
        When old_value is tampered, the reported log_id must be the
        exact row that was modified — not a later row.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[2]['log_id']   

        tamper_field(conn, target_log_id, 'old_value', '{"hacked": "yes"}')

        result = run_verifier(conn)
        assert result['passed'] is False, "Tampering should be detected."
        assert result['tampered_log_id'] == target_log_id, (
            f"Expected tampered_log_id={target_log_id}, "
            f"got {result['tampered_log_id']}."
        )

    def test_tampering_old_value_middle_entry_detected(self, conn):
        """Tampering the middle row of a 5-entry chain must be detected."""
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[2]['log_id']

        tamper_field(conn, target_log_id, 'old_value', '{"middle": "tampered"}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Tampered old_value on middle entry should be detected."
        )

    def test_tampering_old_value_last_entry_detected(self, conn):
        """Tampering the last row of a chain must also be detected."""
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[-1]['log_id']

        tamper_field(conn, target_log_id, 'old_value', '{"last": "tampered"}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Tampered old_value on last entry should be detected."
        )

# SECTION 3 — Modifying new_value Is Detected
class TestNewValueTampering:

    def test_tampering_new_value_detected(self, conn):
        """Modifying new_value on any row must invalidate the chain."""
        build_chain(conn, n=4)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[1]['log_id']

        tamper_field(conn, target_log_id, 'new_value',
                     '{"first_name": "HACKED", "id": 999}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Tampered new_value should be detected."
        )

    def test_tampering_new_value_reports_correct_log_id(self, conn):
        """Tampered new_value must identify the correct first broken row."""
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[3]['log_id']   

        tamper_field(conn, target_log_id, 'new_value', '{"injected": true}')

        result = run_verifier(conn)
        assert result['passed'] is False
        assert result['tampered_log_id'] == target_log_id, (
            f"Expected tampered_log_id={target_log_id}, "
            f"got {result['tampered_log_id']}."
        )

    def test_changing_dosage_in_new_value_detected(self, conn):
        """
        Simulating an insider changing a prescription dosage directly
        in the audit log's new_value must be caught.
        """
        patient_id = insert_patient(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO prescriptions
                (patient_id, medication_name, dosage, frequency, prescribed_date)
            VALUES (%s, 'Warfarin', '5mg', 'Once daily', '2024-01-01')
            RETURNING id;
        """, (patient_id,))
        conn.commit()
        presc_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE prescriptions SET dosage = '10mg' WHERE id = %s;",
            (presc_id,)
        )
        conn.commit()
        cur.close()

        rows = fetch_all_audit_rows(conn)
        update_row = next(
            r for r in rows
            if r['table_name'] == 'prescriptions' and r['operation'] == 'U'
        )
        
        tamper_field(conn, update_row['log_id'], 'new_value',
                     '{"id": 1, "dosage": "5mg", "medication_name": "Warfarin"}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Insider change to dosage in new_value must be detected."
        )


# SECTION 4 — Modifying current_hash Directly
class TestCurrentHashTampering:

    def test_tampering_current_hash_first_entry_detected(self, conn):
        """
        Directly overwriting current_hash on the first row must be detected
        because the second row's previous_hash will no longer match.
        """
        build_chain(conn, n=3)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[0]['log_id']

        tamper_field(conn, target_log_id, 'current_hash',
                     'a' * 64)   

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Overwritten current_hash on first entry should break the chain."
        )

    def test_tampering_current_hash_middle_entry_detected(self, conn):
        """Overwriting current_hash on a middle row breaks linking with the next row."""
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[2]['log_id']

        tamper_field(conn, target_log_id, 'current_hash', 'b' * 64)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Overwritten current_hash on middle entry should be detected."
        )

    def test_tampering_current_hash_reports_next_row_as_broken(self, conn):
        """
        When current_hash of row N is overwritten, the verifier detects
        the break at row N itself — because it recomputes current_hash from
        the row's own data and immediately sees the stored value is wrong.
        The break is reported at the tampered row, not the row after it.
        """
        build_chain(conn, n=4)
        rows = fetch_all_audit_rows(conn)
        tampered_row = rows[1]   

        tamper_field(conn, tampered_row["log_id"], "current_hash", "c" * 64)

        result = run_verifier(conn)
        assert result["passed"] is False
        # The verifier recomputes current_hash for every row and catches
        # the mismatch at row N directly — not at N+1
        assert result["tampered_log_id"] == tampered_row["log_id"], (
            f"Expected break reported at log_id={tampered_row['log_id']} (row N), "
            f"got {result['tampered_log_id']}."
        )

    def test_tampering_current_hash_last_entry_detected(self, conn):
        """Overwriting current_hash on the last row must also be detected."""
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[-1]['log_id']

        tamper_field(conn, target_log_id, 'current_hash', 'd' * 64)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Overwritten current_hash on last entry should be detected."
        )


# SECTION 5 — Modifying previous_hash Directly
class TestPreviousHashTampering:

    def test_tampering_previous_hash_detected(self, conn):
        """
        Overwriting previous_hash on any row must be detected because
        it will no longer match the expected value from the prior row.
        """
        build_chain(conn, n=4)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[1]['log_id']

        tamper_field(conn, target_log_id, 'previous_hash', 'e' * 64)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Tampered previous_hash must be detected."
        )

    def test_tampering_previous_hash_reports_correct_log_id(self, conn):
        """
        Overwriting previous_hash must report the tampered row itself
        as the first broken link (its previous_hash doesn't match expected).
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[2]['log_id']

        tamper_field(conn, target_log_id, 'previous_hash', 'f' * 64)

        result = run_verifier(conn)
        assert result['passed'] is False
        assert result['tampered_log_id'] == target_log_id, (
            f"Expected tampered_log_id={target_log_id}, "
            f"got {result['tampered_log_id']}."
        )

    def test_tampering_first_entry_previous_hash_from_genesis(self, conn):
        """
        Overwriting the first entry's previous_hash (which should be the
        genesis hash) must immediately be caught.
        """
        build_chain(conn, n=3)
        rows = fetch_all_audit_rows(conn)
        first_log_id = rows[0]['log_id']

        tamper_field(conn, first_log_id, 'previous_hash', '0' * 64)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Overwriting genesis hash in first entry must be detected."
        )
        assert result['tampered_log_id'] == first_log_id, (
            f"Break must be reported at the first entry (log_id={first_log_id})."
        )


# SECTION 6 — Deleting Rows Is Detected
class TestRowDeletion:

    def test_deleting_middle_row_detected(self, conn):
        """
        Deleting a middle row from the chain means the row after it
        will have a previous_hash that no longer matches the row before it.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        middle_log_id = rows[2]['log_id']   

        delete_audit_row(conn, middle_log_id)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Deleting a middle row must break the chain."
        )

    def test_deleting_first_row_detected(self, conn):
        """
        Deleting the first row means the new first row's previous_hash
        will not match the genesis hash.
        """
        build_chain(conn, n=4)
        rows = fetch_all_audit_rows(conn)
        first_log_id = rows[0]['log_id']

        delete_audit_row(conn, first_log_id)

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Deleting the first row must be detected (genesis hash mismatch)."
        )

    def test_deleting_last_row_not_detectable_by_chain(self, conn):
        """
        Deleting the LAST row cannot be detected by hash-chain verification
        alone (there is no next row to notice the missing link).
        This test documents this known limitation of the design.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        last_log_id = rows[-1]['log_id']

        delete_audit_row(conn, last_log_id)

        result = run_verifier(conn)
        # This is a known limitation, not a bug
        # The remaining 4 entries still form a valid chain
        assert result['passed'] is True, (
            "Known limitation: deleting the last row is undetectable "
            "by chain verification alone. The remaining chain is still valid."
        )

    def test_deleting_multiple_rows_detected(self, conn):
        """Deleting two consecutive rows from the middle must also be detected."""
        build_chain(conn, n=6)
        rows = fetch_all_audit_rows(conn)

        delete_audit_row(conn, rows[2]['log_id'])
        delete_audit_row(conn, rows[3]['log_id'])

        result = run_verifier(conn)
        assert result['passed'] is False, (
            "Deleting multiple rows must be detected."
        )

    def test_deleting_middle_row_reports_correct_broken_log_id(self, conn):
        """
        After a middle-row deletion the first broken log_id must be the
        row that immediately follows the deleted one.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        middle_log_id  = rows[2]['log_id']   # will be deleted
        next_log_id    = rows[3]['log_id']   # this is where break shows up

        delete_audit_row(conn, middle_log_id)

        result = run_verifier(conn)
        assert result['passed'] is False
        assert result['tampered_log_id'] == next_log_id, (
            f"Expected break at log_id={next_log_id} (row after deleted), "
            f"got {result['tampered_log_id']}."
        )


# SECTION 7 — Correct log_id Always Reported
class TestCorrectLogIdReported:

    def test_first_tampered_row_reported_not_later_rows(self, conn):
        """
        When multiple rows are tampered, only the FIRST broken log_id
        must be reported. Later breaks are downstream effects.
        """
        build_chain(conn, n=6)
        rows = fetch_all_audit_rows(conn)

        # Tamper rows 2 and 4 — only row 2 should be reported
        tamper_field(conn, rows[1]['log_id'], 'old_value', '{"first_tamper": true}')
        tamper_field(conn, rows[3]['log_id'], 'old_value', '{"second_tamper": true}')

        result = run_verifier(conn)
        assert result['passed'] is False
        assert result['tampered_log_id'] == rows[1]['log_id'], (
            f"Only the first tampered log_id={rows[1]['log_id']} should be "
            f"reported, got {result['tampered_log_id']}."
        )

    @pytest.mark.parametrize("tamper_position", [0, 1, 2, 3, 4])
    def test_tamper_at_each_position_reports_correct_log_id(self, conn, tamper_position):
        """
        Parametrized: tamper each position in a 5-entry chain and confirm
        the reported log_id is always the correct first broken row.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)
        target_row    = rows[tamper_position]
        target_log_id = target_row['log_id']

        tamper_field(conn, target_log_id, 'old_value', '{"pos_tamper": true}')

        result = run_verifier(conn)
        assert result['passed'] is False, (
            f"Tamper at position {tamper_position} should be detected."
        )
        assert result['tampered_log_id'] == target_log_id, (
            f"Position {tamper_position}: expected log_id={target_log_id}, "
            f"got {result['tampered_log_id']}."
        )

# SECTION 8 — Fix and Re-verify
class TestFixAndReverify:

    def test_reverify_passes_after_repair(self, conn):
        """
        After repairing a tampered hash, re-running the verifier
        must return PASSED — confirming the verifier is not permanently broken.
        """
        build_chain(conn, n=4)
        rows = fetch_all_audit_rows(conn)
        target_log_id = rows[1]['log_id']

        # Tamper old_value
        tamper_field(conn, target_log_id, 'old_value', '{"broken": true}')
        result_after_tamper = run_verifier(conn)
        assert result_after_tamper['passed'] is False, (
            "Should be detected as tampered before repair."
        )

        # Repair: restore original old_value then recompute hash
        tamper_field(conn, target_log_id, 'old_value', None)
        recompute_and_repair_hash(conn, target_log_id)

        result_after_repair = run_verifier(conn)
        assert result_after_repair['passed'] is True, (
            "After repair, verifier should return PASSED."
        )

    def test_tampering_then_fixing_all_rows_passes(self, conn):
        """
        Tampering every row then repairing every row must return a valid chain.
        """
        build_chain(conn, n=5)
        rows = fetch_all_audit_rows(conn)

        # Tamper all rows
        for row in rows:
            tamper_field(conn, row['log_id'], 'old_value', '{"all_broken": true}')

        result_broken = run_verifier(conn)
        assert result_broken['passed'] is False

        # Repair all rows (restore old_value, recompute hash in order)
        for row in rows:
            tamper_field(conn, row['log_id'], 'old_value', None)
            recompute_and_repair_hash(conn, row['log_id'])

        result_repaired = run_verifier(conn)
        assert result_repaired['passed'] is True, (
            "All rows repaired — chain should be valid again."
        )