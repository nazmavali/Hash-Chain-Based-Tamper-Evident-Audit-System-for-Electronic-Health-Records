"""
Test File 1 — Part A: Database Schema Validation

Covers:
  - Required tables exist (patients, prescriptions, audit_log)
  - All required columns are present with correct data types
  - Required indexes exist
  - pgcrypto extension is enabled
  - Foreign key constraint (prescriptions → patients) works correctly
"""

import pytest
import psycopg2

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
    """Establish a single DB connection for all tests in this module."""
    connection = psycopg2.connect(**DB_PARAMS)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def cursor(conn):
    """Provide a cursor from the shared connection."""
    cur = conn.cursor()
    yield cur
    cur.close()

# Helper
def get_columns(cursor, table_name):
    """Return a dict of {column_name: data_type} for the given table."""
    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = %s;
    """, (table_name,))
    return {row[0]: row[1] for row in cursor.fetchall()}


# SECTION 1 — Tables Exist
class TestTablesExist:

    def test_patients_table_exists(self, cursor):
        """patients table must exist in the public schema."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'patients'
            );
        """)
        assert cursor.fetchone()[0], "Table 'patients' does not exist."

    def test_prescriptions_table_exists(self, cursor):
        """prescriptions table must exist in the public schema."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'prescriptions'
            );
        """)
        assert cursor.fetchone()[0], "Table 'prescriptions' does not exist."

    def test_audit_log_table_exists(self, cursor):
        """audit_log table must exist in the public schema."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'audit_log'
            );
        """)
        assert cursor.fetchone()[0], "Table 'audit_log' does not exist."


# SECTION 2 — Columns and Data Types
class TestPatientsColumns:
    """Verify every required column exists in the patients table."""

    # Expected column → acceptable data type(s)
    EXPECTED_COLUMNS = {
        'id':            ['integer'],
        'first_name':    ['character varying'],
        'last_name':     ['character varying'],
        'date_of_birth': ['date'],
        'gender':        ['character'],
        'email':         ['character varying'],
        'phone':         ['character varying'],
        'address':       ['text'],
        'blood_type':    ['character varying'],
        'created_at':    ['timestamp without time zone'],
    }

    def test_patients_has_all_columns(self, cursor):
        """All required columns must be present in patients."""
        columns = get_columns(cursor, 'patients')
        for col in self.EXPECTED_COLUMNS:
            assert col in columns, f"Missing column '{col}' in patients table."

    @pytest.mark.parametrize("col,expected_types", EXPECTED_COLUMNS.items())
    def test_patients_column_types(self, cursor, col, expected_types):
        """Each patients column must have the correct data type."""
        columns = get_columns(cursor, 'patients')
        if col in columns:
            assert columns[col] in expected_types, (
                f"Column '{col}' in patients: expected {expected_types}, "
                f"got '{columns[col]}'."
            )


class TestPrescriptionsColumns:
    """Verify every required column exists in the prescriptions table."""

    EXPECTED_COLUMNS = {
        'id':              ['integer'],
        'patient_id':      ['integer'],
        'medication_name': ['character varying'],
        'dosage':          ['character varying'],
        'frequency':       ['character varying'],
        'prescribed_date': ['date'],
        'end_date':        ['date'],
        'refills_left':    ['integer'],
        'status':          ['character varying'],
        'instructions':    ['text'],
        'created_at':      ['timestamp without time zone'],
    }

    def test_prescriptions_has_all_columns(self, cursor):
        """All required columns must be present in prescriptions."""
        columns = get_columns(cursor, 'prescriptions')
        for col in self.EXPECTED_COLUMNS:
            assert col in columns, f"Missing column '{col}' in prescriptions table."

    @pytest.mark.parametrize("col,expected_types", EXPECTED_COLUMNS.items())
    def test_prescriptions_column_types(self, cursor, col, expected_types):
        """Each prescriptions column must have the correct data type."""
        columns = get_columns(cursor, 'prescriptions')
        if col in columns:
            assert columns[col] in expected_types, (
                f"Column '{col}' in prescriptions: expected {expected_types}, "
                f"got '{columns[col]}'."
            )


class TestAuditLogColumns:
    """Verify every required column exists in the audit_log table."""

    EXPECTED_COLUMNS = {
        'log_id':        ['integer'],
        'table_name':    ['character varying'],
        'record_id':     ['integer'],
        'operation':     ['character'],
        'old_value':     ['jsonb'],
        'new_value':     ['jsonb'],
        'changed_at':    ['timestamp with time zone'],
        'changed_by':    ['character varying'],
        'previous_hash': ['character'],
        'current_hash':  ['character'],
    }

    def test_audit_log_has_all_columns(self, cursor):
        """All required columns must be present in audit_log."""
        columns = get_columns(cursor, 'audit_log')
        for col in self.EXPECTED_COLUMNS:
            assert col in columns, f"Missing column '{col}' in audit_log table."

    @pytest.mark.parametrize("col,expected_types", EXPECTED_COLUMNS.items())
    def test_audit_log_column_types(self, cursor, col, expected_types):
        """Each audit_log column must have the correct data type."""
        columns = get_columns(cursor, 'audit_log')
        if col in columns:
            assert columns[col] in expected_types, (
                f"Column '{col}' in audit_log: expected {expected_types}, "
                f"got '{columns[col]}'."
            )

# SECTION 3 — Indexes Exist
class TestIndexesExist:
    """Verify all performance indexes are created."""

    EXPECTED_INDEXES = [
        'idx_prescriptions_patient_id',
        'idx_prescriptions_status',
        'idx_patients_last_name',
        'idx_audit_log_table_record',
        'idx_audit_log_changed_at',
        'idx_audit_log_chain',
    ]

    @pytest.mark.parametrize("index_name", EXPECTED_INDEXES)
    def test_index_exists(self, cursor, index_name):
        """Each required index must exist in pg_indexes."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname  = %s
            );
        """, (index_name,))
        assert cursor.fetchone()[0], f"Index '{index_name}' does not exist."


# SECTION 4 — pgcrypto Extension
class TestPgcryptoExtension:

    def test_pgcrypto_is_enabled(self, cursor):
        """pgcrypto extension must be installed and enabled."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_extension
                WHERE extname = 'pgcrypto'
            );
        """)
        assert cursor.fetchone()[0], (
            "Extension 'pgcrypto' is not enabled. "
            "Run: CREATE EXTENSION IF NOT EXISTS pgcrypto;"
        )

    def test_sha256_function_works(self, cursor):
        """pgcrypto's digest() must return a 64-char hex SHA-256 hash."""
        cursor.execute("SELECT encode(digest('test', 'sha256'), 'hex');")
        result = cursor.fetchone()[0]
        assert len(result) == 64, (
            f"SHA-256 hash should be 64 hex chars, got {len(result)}."
        )
        assert result == '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08', (
            "SHA-256 of 'test' did not match expected value."
        )

# SECTION 5 — Foreign Key Constraint
class TestForeignKeyConstraint:

    def test_fk_prescriptions_to_patients_exists(self, cursor):
        """A foreign key from prescriptions.patient_id → patients.id must exist."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                  ON rc.constraint_name = kcu.constraint_name
                WHERE kcu.table_name   = 'prescriptions'
                  AND kcu.column_name  = 'patient_id'
            );
        """)
        assert cursor.fetchone()[0], (
            "Foreign key from prescriptions.patient_id to patients.id does not exist."
        )

    def test_fk_rejects_invalid_patient_id(self, conn, cursor):
        """Inserting a prescription with a non-existent patient_id must be rejected."""
        # Temporarily disable autocommit so we can rollback cleanly
        conn.autocommit = False
        try:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cursor.execute("""
                    INSERT INTO prescriptions
                        (patient_id, medication_name, dosage, frequency, prescribed_date)
                    VALUES
                        (999999999, 'TestDrug', '10mg', 'Once daily', '2024-01-01');
                """)
                conn.commit()
        finally:
            conn.rollback()      
            conn.autocommit = True

    def test_cascade_delete_removes_prescriptions(self, conn, cursor):
        """Deleting a patient must cascade-delete their prescriptions."""
        conn.autocommit = False
        try:
            cursor.execute("""
                INSERT INTO patients (first_name, last_name, date_of_birth, gender)
                VALUES ('Test', 'Cascade', '1990-01-01', 'M')
                RETURNING id;
            """)
            patient_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO prescriptions
                    (patient_id, medication_name, dosage, frequency, prescribed_date)
                VALUES
                    (%s, 'TestDrug', '10mg', 'Once daily', '2024-01-01');
            """, (patient_id,))

            cursor.execute("DELETE FROM patients WHERE id = %s;", (patient_id,))
            conn.commit()

            cursor.execute(
                "SELECT COUNT(*) FROM prescriptions WHERE patient_id = %s;",
                (patient_id,)
            )
            count = cursor.fetchone()[0]
            assert count == 0, (
                f"Expected 0 prescriptions after cascade delete, found {count}."
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.rollback()     
            conn.autocommit = True