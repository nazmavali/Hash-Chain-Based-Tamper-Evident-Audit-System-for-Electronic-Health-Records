"""
Test File 3 — Part B (Step 4): Trigger Validation

Covers:
  - Triggers exist and are enabled on both patients and prescriptions
  - INSERT on patients/prescriptions creates an audit entry with operation='I'
  - UPDATE creates an audit entry with operation='U' and correct old/new values
  - DELETE creates an audit entry with operation='D' and correct old value
  - Audit entries capture the correct table_name and record_id
  - old_value is NULL for INSERT, new_value is NULL for DELETE
  - Multiple operations on the same record each produce their own audit entry
  - Triggers fire independently on both tables in the same transaction
"""

import pytest
import psycopg2
import psycopg2.extras
import json

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
    Before and after every test:
      - Clear audit_log, prescriptions, patients
      - Re-enable both triggers in case a test disabled them
      - Reset sequences so IDs are predictable
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
def insert_patient(cursor, conn,
                   first_name='Jane', last_name='Smith',
                   dob='1990-05-15', gender='F'):
    """Insert a patient and return its id."""
    cursor.execute("""
        INSERT INTO patients (first_name, last_name, date_of_birth, gender)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
    """, (first_name, last_name, dob, gender))
    conn.commit()
    return cursor.fetchone()['id']


def insert_prescription(cursor, conn, patient_id,
                         medication='Lisinopril', dosage='10mg',
                         frequency='Once daily', date='2024-01-01'):
    """Insert a prescription and return its id."""
    cursor.execute("""
        INSERT INTO prescriptions
            (patient_id, medication_name, dosage, frequency, prescribed_date)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
    """, (patient_id, medication, dosage, frequency, date))
    conn.commit()
    return cursor.fetchone()['id']


def fetch_audit_rows(cursor, table_name=None, record_id=None):
    """
    Fetch audit_log rows ordered by log_id.
    """
    query = """
        SELECT
            log_id,
            table_name,
            record_id,
            operation,
            old_value,
            new_value,
            changed_by,
            previous_hash,
            current_hash
        FROM audit_log
        WHERE 1=1
    """
    params = []
    if table_name:
        query += " AND table_name = %s"
        params.append(table_name)
    if record_id is not None:
        query += " AND record_id = %s"
        params.append(record_id)
    query += " ORDER BY log_id ASC;"
    cursor.execute(query, params)
    return cursor.fetchall()

# SECTION 1 — Triggers Exist and Are Enabled
class TestTriggersExistAndEnabled:

    EXPECTED_TRIGGERS = [
        ('patients',      'patients_audit_trigger'),
        ('prescriptions', 'prescriptions_audit_trigger'),
    ]

    @pytest.mark.parametrize("table,trigger_name", EXPECTED_TRIGGERS)
    def test_trigger_exists(self, cursor, conn, table, trigger_name):
        """Each audit trigger must exist in pg_trigger."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                WHERE c.relname  = %s
                  AND t.tgname   = %s
            );
        """, (table, trigger_name))
        assert cursor.fetchone()['exists'], (
            f"Trigger '{trigger_name}' does not exist on table '{table}'."
        )

    @pytest.mark.parametrize("table,trigger_name", EXPECTED_TRIGGERS)
    def test_trigger_is_enabled(self, cursor, conn, table, trigger_name):
        """Each audit trigger must be in enabled state ('O' = enabled in pg_trigger)."""
        cursor.execute("""
            SELECT t.tgenabled
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relname = %s
              AND t.tgname  = %s;
        """, (table, trigger_name))
        row = cursor.fetchone()
        assert row is not None, f"Trigger '{trigger_name}' not found."
        # 'O' = fires in origin and local mode (enabled), 'D' = disabled
        assert row['tgenabled'] != 'D', (
            f"Trigger '{trigger_name}' on '{table}' is disabled."
        )

    def test_trigger_function_exists(self, cursor, conn):
        """The audit_trigger_fn() function must exist in pg_proc."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_proc
                WHERE proname = 'audit_trigger_fn'
            );
        """)
        assert cursor.fetchone()['exists'], (
            "Trigger function 'audit_trigger_fn' does not exist."
        )


# SECTION 2 — INSERT Triggers
class TestInsertTriggers:

    def test_patient_insert_creates_audit_entry(self, cursor, conn):
        """Inserting a patient must produce exactly one audit entry."""
        insert_patient(cursor, conn)
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert len(rows) == 1, (
            f"Expected 1 audit entry after patient INSERT, found {len(rows)}."
        )

    def test_patient_insert_operation_is_I(self, cursor, conn):
        """Patient INSERT audit entry must have operation = 'I'."""
        insert_patient(cursor, conn)
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert rows[0]['operation'].strip() == 'I', (
            f"Expected operation='I', got '{rows[0]['operation']}'."
        )

    def test_patient_insert_old_value_is_null(self, cursor, conn):
        """Patient INSERT audit entry must have old_value = NULL."""
        insert_patient(cursor, conn)
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert rows[0]['old_value'] is None, (
            f"Expected old_value=NULL for INSERT, got: {rows[0]['old_value']}"
        )

    def test_patient_insert_new_value_contains_data(self, cursor, conn):
        """Patient INSERT audit entry's new_value must contain the inserted data."""
        insert_patient(cursor, conn, first_name='Alice', last_name='Wonder')
        rows = fetch_audit_rows(cursor, table_name='patients')
        new_val = rows[0]['new_value']
        assert new_val is not None, "new_value should not be NULL for INSERT."
        assert new_val.get('first_name') == 'Alice', (
            f"new_value should contain first_name='Alice', got: {new_val}"
        )
        assert new_val.get('last_name') == 'Wonder', (
            f"new_value should contain last_name='Wonder', got: {new_val}"
        )

    def test_patient_insert_captures_correct_record_id(self, cursor, conn):
        """Audit entry's record_id must match the inserted patient's id."""
        patient_id = insert_patient(cursor, conn)
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert rows[0]['record_id'] == patient_id, (
            f"Expected record_id={patient_id}, got {rows[0]['record_id']}."
        )

    def test_patient_insert_captures_correct_table_name(self, cursor, conn):
        """Audit entry must record table_name = 'patients'."""
        insert_patient(cursor, conn)
        rows = fetch_audit_rows(cursor)
        assert rows[0]['table_name'] == 'patients', (
            f"Expected table_name='patients', got '{rows[0]['table_name']}'."
        )

    def test_prescription_insert_creates_audit_entry(self, cursor, conn):
        """Inserting a prescription must produce an audit entry with operation='I'."""
        patient_id = insert_patient(cursor, conn)
        insert_prescription(cursor, conn, patient_id)
        rows = fetch_audit_rows(cursor, table_name='prescriptions')
        assert len(rows) == 1, (
            f"Expected 1 audit entry for prescription INSERT, found {len(rows)}."
        )
        assert rows[0]['operation'].strip() == 'I', (
            f"Expected operation='I', got '{rows[0]['operation']}'."
        )

    def test_prescription_insert_new_value_contains_medication(self, cursor, conn):
        """Prescription INSERT audit entry must capture medication_name in new_value."""
        patient_id = insert_patient(cursor, conn)
        insert_prescription(cursor, conn, patient_id, medication='Metformin', dosage='500mg')
        rows = fetch_audit_rows(cursor, table_name='prescriptions')
        new_val = rows[0]['new_value']
        assert new_val is not None, "new_value should not be NULL for prescription INSERT."
        assert new_val.get('medication_name') == 'Metformin', (
            f"Expected medication_name='Metformin', got: {new_val.get('medication_name')}"
        )
        assert new_val.get('dosage') == '500mg', (
            f"Expected dosage='500mg', got: {new_val.get('dosage')}"
        )

    def test_prescription_insert_captures_correct_record_id(self, cursor, conn):
        """Prescription audit entry's record_id must match the inserted prescription's id."""
        patient_id = insert_patient(cursor, conn)
        presc_id = insert_prescription(cursor, conn, patient_id)
        rows = fetch_audit_rows(cursor, table_name='prescriptions')
        assert rows[0]['record_id'] == presc_id, (
            f"Expected record_id={presc_id}, got {rows[0]['record_id']}."
        )


# SECTION 3 — UPDATE Triggers
class TestUpdateTriggers:

    def test_patient_update_creates_audit_entry(self, cursor, conn):
        """Updating a patient must add one more audit entry (total = 2)."""
        patient_id = insert_patient(cursor, conn, first_name='Bob')
        cursor.execute(
            "UPDATE patients SET first_name = 'Robert' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert len(rows) == 2, (
            f"Expected 2 audit entries (INSERT + UPDATE), found {len(rows)}."
        )

    def test_patient_update_operation_is_U(self, cursor, conn):
        """Patient UPDATE audit entry must have operation = 'U'."""
        patient_id = insert_patient(cursor, conn, first_name='Bob')
        cursor.execute(
            "UPDATE patients SET first_name = 'Robert' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        update_row = rows[1]   
        assert update_row['operation'].strip() == 'U', (
            f"Expected operation='U', got '{update_row['operation']}'."
        )

    def test_patient_update_old_value_has_original_data(self, cursor, conn):
        """UPDATE audit entry's old_value must contain the BEFORE state."""
        patient_id = insert_patient(cursor, conn, first_name='Bob')
        cursor.execute(
            "UPDATE patients SET first_name = 'Robert' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        old_val = rows[1]['old_value']
        assert old_val is not None, "old_value must not be NULL for UPDATE."
        assert old_val.get('first_name') == 'Bob', (
            f"old_value should contain original first_name='Bob', got: {old_val}"
        )

    def test_patient_update_new_value_has_updated_data(self, cursor, conn):
        """UPDATE audit entry's new_value must contain the AFTER state."""
        patient_id = insert_patient(cursor, conn, first_name='Bob')
        cursor.execute(
            "UPDATE patients SET first_name = 'Robert' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        new_val = rows[1]['new_value']
        assert new_val is not None, "new_value must not be NULL for UPDATE."
        assert new_val.get('first_name') == 'Robert', (
            f"new_value should contain updated first_name='Robert', got: {new_val}"
        )

    def test_patient_update_old_and_new_values_differ(self, cursor, conn):
        """old_value and new_value in an UPDATE entry must not be identical."""
        patient_id = insert_patient(cursor, conn, first_name='Bob')
        cursor.execute(
            "UPDATE patients SET first_name = 'Robert' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert rows[1]['old_value'] != rows[1]['new_value'], (
            "old_value and new_value are identical — UPDATE was not captured correctly."
        )

    def test_prescription_update_dosage_captured(self, cursor, conn):
        """Updating a prescription's dosage must be reflected in the audit's new_value."""
        patient_id = insert_patient(cursor, conn)
        presc_id   = insert_prescription(cursor, conn, patient_id, dosage='10mg')
        cursor.execute(
            "UPDATE prescriptions SET dosage = '20mg' WHERE id = %s;",
            (presc_id,)
        )
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='prescriptions')
        update_row = rows[1]
        assert update_row['operation'].strip() == 'U'
        assert update_row['old_value'].get('dosage') == '10mg', (
            f"Expected old dosage='10mg', got: {update_row['old_value'].get('dosage')}"
        )
        assert update_row['new_value'].get('dosage') == '20mg', (
            f"Expected new dosage='20mg', got: {update_row['new_value'].get('dosage')}"
        )

    def test_multiple_updates_each_produce_audit_entry(self, cursor, conn):
        """Three consecutive updates on the same patient must each create an audit entry."""
        patient_id = insert_patient(cursor, conn, first_name='Version1')
        for version in ['Version2', 'Version3', 'Version4']:
            cursor.execute(
                "UPDATE patients SET first_name = %s WHERE id = %s;",
                (version, patient_id)
            )
            conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        # 1 INSERT + 3 UPDATEs = 4 total
        assert len(rows) == 4, (
            f"Expected 4 audit entries (1 INSERT + 3 UPDATEs), found {len(rows)}."
        )
        operations = [r['operation'].strip() for r in rows]
        assert operations == ['I', 'U', 'U', 'U'], (
            f"Expected ['I','U','U','U'], got {operations}."
        )


# SECTION 4 — DELETE Triggers
class TestDeleteTriggers:

    def test_patient_delete_creates_audit_entry(self, cursor, conn):
        """Deleting a patient must add one more audit entry."""
        patient_id = insert_patient(cursor, conn)
        cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert len(rows) == 2, (
            f"Expected 2 audit entries (INSERT + DELETE), found {len(rows)}."
        )

    def test_patient_delete_operation_is_D(self, cursor, conn):
        """Patient DELETE audit entry must have operation = 'D'."""
        patient_id = insert_patient(cursor, conn)
        cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        delete_row = rows[1]
        assert delete_row['operation'].strip() == 'D', (
            f"Expected operation='D', got '{delete_row['operation']}'."
        )

    def test_patient_delete_new_value_is_null(self, cursor, conn):
        """DELETE audit entry must have new_value = NULL."""
        patient_id = insert_patient(cursor, conn)
        cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        assert rows[1]['new_value'] is None, (
            f"Expected new_value=NULL for DELETE, got: {rows[1]['new_value']}"
        )

    def test_patient_delete_old_value_has_deleted_data(self, cursor, conn):
        """DELETE audit entry's old_value must contain the row that was deleted."""
        patient_id = insert_patient(cursor, conn, first_name='Charlie', last_name='Brown')
        cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='patients')
        old_val = rows[1]['old_value']
        assert old_val is not None, "old_value must not be NULL for DELETE."
        assert old_val.get('first_name') == 'Charlie', (
            f"old_value should contain first_name='Charlie', got: {old_val}"
        )
        assert old_val.get('last_name') == 'Brown', (
            f"old_value should contain last_name='Brown', got: {old_val}"
        )

    def test_prescription_delete_captured(self, cursor, conn):
        """Deleting a prescription must create a DELETE audit entry on prescriptions."""
        patient_id = insert_patient(cursor, conn)
        presc_id   = insert_prescription(cursor, conn, patient_id, medication='Warfarin')
        cursor.execute("DELETE FROM prescriptions WHERE id = %s;", (presc_id,))
        conn.commit()
        rows = fetch_audit_rows(cursor, table_name='prescriptions')
        delete_row = rows[1]
        assert delete_row['operation'].strip() == 'D', (
            f"Expected operation='D' for prescription delete, got '{delete_row['operation']}'."
        )
        assert delete_row['old_value'].get('medication_name') == 'Warfarin', (
            f"old_value should contain medication_name='Warfarin'."
        )
        assert delete_row['new_value'] is None, "new_value must be NULL for DELETE."


# SECTION 5 — Both Tables Fire Independently
class TestBothTablesFireIndependently:

    def test_operations_on_both_tables_all_produce_audit_entries(self, cursor, conn):
        """
        Performing INSERT on both patients and prescriptions must produce
        separate audit entries, one per table, correctly labelled.
        """
        patient_id = insert_patient(cursor, conn)
        insert_prescription(cursor, conn, patient_id)
        all_rows = fetch_audit_rows(cursor)
        # 1 patient INSERT + 1 prescription INSERT = 2 total
        assert len(all_rows) == 2, (
            f"Expected 2 audit entries total, found {len(all_rows)}."
        )
        table_names = {r['table_name'] for r in all_rows}
        assert 'patients'      in table_names, "No audit entry for 'patients'."
        assert 'prescriptions' in table_names, "No audit entry for 'prescriptions'."

    def test_audit_entry_counts_per_table_are_correct(self, cursor, conn):
        """
        Insert 1 patient and 2 prescriptions → audit_log must have
        exactly 1 patients entry and 2 prescriptions entries.
        """
        patient_id = insert_patient(cursor, conn)
        insert_prescription(cursor, conn, patient_id, medication='Drug A')
        insert_prescription(cursor, conn, patient_id, medication='Drug B')

        patient_rows = fetch_audit_rows(cursor, table_name='patients')
        presc_rows   = fetch_audit_rows(cursor, table_name='prescriptions')

        assert len(patient_rows) == 1, (
            f"Expected 1 patients audit entry, found {len(patient_rows)}."
        )
        assert len(presc_rows) == 2, (
            f"Expected 2 prescriptions audit entries, found {len(presc_rows)}."
        )

    def test_full_lifecycle_insert_update_delete_both_tables(self, cursor, conn):
        """
        Full lifecycle on both tables:
          Patient:      INSERT → UPDATE → DELETE  (3 entries)
          Prescription: INSERT → UPDATE → DELETE  (3 entries)
        Total audit entries expected: 6
        """
        # Patient lifecycle
        patient_id = insert_patient(cursor, conn, first_name='Lifecycle')
        cursor.execute(
            "UPDATE patients SET first_name = 'LifecycleUpdated' WHERE id = %s;",
            (patient_id,)
        )
        conn.commit()

        # Prescription lifecycle (must insert before patient delete due to FK)
        presc_id = insert_prescription(cursor, conn, patient_id, medication='TestDrug')
        cursor.execute(
            "UPDATE prescriptions SET dosage = '99mg' WHERE id = %s;",
            (presc_id,)
        )
        conn.commit()
        cursor.execute("DELETE FROM prescriptions WHERE id = %s;", (presc_id,))
        conn.commit()

        # Now delete patient
        cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
        conn.commit()

        all_rows = fetch_audit_rows(cursor)
        assert len(all_rows) == 6, (
            f"Expected 6 total audit entries (3 per table), found {len(all_rows)}."
        )

        patient_ops = [
            r['operation'].strip()
            for r in all_rows if r['table_name'] == 'patients'
        ]
        presc_ops = [
            r['operation'].strip()
            for r in all_rows if r['table_name'] == 'prescriptions'
        ]

        assert patient_ops == ['I', 'U', 'D'], (
            f"Expected patient ops ['I','U','D'], got {patient_ops}."
        )
        assert presc_ops == ['I', 'U', 'D'], (
            f"Expected prescription ops ['I','U','D'], got {presc_ops}."
        )

    def test_disabling_one_trigger_does_not_affect_the_other(self, cursor, conn):
        """
        Disabling the patients trigger must NOT stop the prescriptions
        trigger from firing, and vice versa.
        """
        # First, insert a patient WITH trigger enabled (to satisfy FK)
        patient_id = insert_patient(cursor, conn)

        # Now disable the patients trigger
        cur = conn.cursor()
        cur.execute("ALTER TABLE patients DISABLE TRIGGER patients_audit_trigger;")
        conn.commit()

        # Insert another patient — should NOT produce an audit entry
        cur.execute("""
            INSERT INTO patients (first_name, last_name, date_of_birth, gender)
            VALUES ('NoAudit', 'Person', '2000-01-01', 'M')
            RETURNING id;
        """)
        conn.commit()

        # Insert a prescription — prescriptions trigger is still ON
        insert_prescription(cursor, conn, patient_id)

        patient_rows = fetch_audit_rows(cursor, table_name='patients')
        presc_rows   = fetch_audit_rows(cursor, table_name='prescriptions')

        # Only the first patient insert (before disable) should be audited
        assert len(patient_rows) == 1, (
            f"Expected 1 patients audit entry (trigger was disabled for second insert), "
            f"found {len(patient_rows)}."
        )
        assert len(presc_rows) == 1, (
            "Prescriptions trigger should still fire even when patients trigger is disabled."
        )

        # Re-enable for cleanup fixture
        cur.execute("ALTER TABLE patients ENABLE TRIGGER patients_audit_trigger;")
        conn.commit()
        cur.close()