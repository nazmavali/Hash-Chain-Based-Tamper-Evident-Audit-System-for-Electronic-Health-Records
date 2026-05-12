"""
Test File 2 — Part B (Steps 2–3): Hash Chain Logic Validation

Covers:
  - Genesis hash is computed correctly
  - insert_audit_log() function exists and is callable
  - First audit entry uses the genesis hash as its previous_hash
  - SHA-256 hash is computed correctly (matches Python hashlib)
  - Chaining is correct: previous_hash of entry N+1 = current_hash of entry N
  - Hash uniqueness: no two entries share the same current_hash
  - Chain remains intact across multiple consecutive inserts
"""

import pytest
import psycopg2
import psycopg2.extras
import hashlib

# Database connection parameters
DB_PARAMS = {
    'host': 'localhost',
    'database': 'healthcare_db',
    'user': 'postgres',
    'password': '36375213',
    'port': '5432'
}

# The genesis hash must match SHA-256('GENESIS') — same as PostgreSQL's:
# SELECT encode(digest('GENESIS', 'sha256'), 'hex');
GENESIS_HASH = hashlib.sha256(b'GENESIS').hexdigest()

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
    """Cursor using RealDictCursor for readable row access."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield cur
    cur.close()


@pytest.fixture(autouse=True)
def clean_audit_log(conn):
    """
    Before each test: truncate audit_log so every test starts
    with a clean, empty chain. Rolled back after each test so
    patients/prescriptions data is not permanently affected.
    """
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE audit_log RESTART IDENTITY;")
    conn.commit()
    cur.close()
    yield
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE audit_log RESTART IDENTITY;")
    conn.commit()
    cur.close()

# Helper: recompute hash the same way PostgreSQL does
def compute_expected_hash(old_value, new_value, table_name, record_id, operation, previous_hash):
    """
    Mirrors the PostgreSQL hash formula in insert_audit_log():

        SHA-256(
            COALESCE(old_value, '') ||
            COALESCE(new_value, '') ||
            table_name              ||
            record_id::text         ||
            operation               ||
            previous_hash
        )
    """
    data = (
        (old_value or '') +
        (new_value or '') +
        table_name +
        str(record_id) +
        operation +
        previous_hash
    )
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def call_insert_audit_log(cursor, conn, table_name, record_id, operation,
                           old_value=None, new_value=None):
    """
    Directly call the PostgreSQL insert_audit_log() function
    and commit so the row is visible for SELECT queries.
    """
    cursor.execute(
        "SELECT insert_audit_log(%s, %s, %s, %s::jsonb, %s::jsonb);",
        (table_name, record_id, operation, old_value, new_value)
    )
    conn.commit()


def fetch_audit_rows(cursor):
    """Return all audit_log rows ordered by log_id ASC."""
    cursor.execute("""
        SELECT
            log_id,
            table_name,
            record_id,
            operation,
            old_value::text  AS old_value,
            new_value::text  AS new_value,
            previous_hash,
            current_hash
        FROM audit_log
        ORDER BY log_id ASC;
    """)
    return cursor.fetchall()

# SECTION 1 — Genesis Hash
class TestGenesisHash:

    def test_genesis_hash_value_is_correct(self, cursor, conn):
        """
        The genesis hash returned by the audit_genesis_hash view must equal
        SHA-256('GENESIS') computed by Python hashlib.
        """
        cursor.execute("SELECT hash FROM audit_genesis_hash;")
        db_genesis = cursor.fetchone()['hash']
        assert db_genesis == GENESIS_HASH, (
            f"Genesis hash mismatch.\n"
            f"  PostgreSQL: {db_genesis}\n"
            f"  Python:     {GENESIS_HASH}"
        )

    def test_genesis_hash_is_64_hex_chars(self, cursor, conn):
        """Genesis hash must be a valid 64-character hex string (SHA-256)."""
        cursor.execute("SELECT hash FROM audit_genesis_hash;")
        db_genesis = cursor.fetchone()['hash']
        assert len(db_genesis) == 64, (
            f"Genesis hash should be 64 chars, got {len(db_genesis)}."
        )
        assert all(c in '0123456789abcdef' for c in db_genesis), (
            "Genesis hash contains non-hex characters."
        )

    def test_python_genesis_hash_matches_expected(self):
        """
        Sanity check: Python's SHA-256('GENESIS') must equal the
        known constant we use throughout all tests.
        """
        computed = hashlib.sha256(b'GENESIS').hexdigest()
        assert computed == GENESIS_HASH
        assert len(computed) == 64

# SECTION 2 — insert_audit_log() Function Exists
class TestInsertAuditLogFunctionExists:

    def test_function_exists_in_pg_catalog(self, cursor, conn):
        """insert_audit_log() must be present in pg_proc."""
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_proc
                WHERE proname = 'insert_audit_log'
            );
        """)
        assert cursor.fetchone()['exists'], (
            "Function 'insert_audit_log' does not exist in the database."
        )

    def test_function_is_callable_without_error(self, cursor, conn):
        """
        Calling insert_audit_log() with a minimal INSERT payload
        must not raise any exception.
        """
        try:
            call_insert_audit_log(
                cursor, conn,
                table_name='patients',
                record_id=1,
                operation='I',
                old_value=None,
                new_value='{"id": 1, "first_name": "Test"}'
            )
        except Exception as e:
            pytest.fail(f"insert_audit_log() raised an unexpected exception: {e}")

    def test_function_inserts_exactly_one_row(self, cursor, conn):
        """A single call to insert_audit_log() must create exactly one audit row."""
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value='{"id": 1, "first_name": "Test"}'
        )
        rows = fetch_audit_rows(cursor)
        assert len(rows) == 1, (
            f"Expected 1 audit row after one call, found {len(rows)}."
        )

# SECTION 3 — First Entry Uses Genesis Hash
class TestFirstEntryUsesGenesisHash:

    def test_first_entry_previous_hash_is_genesis(self, cursor, conn):
        """
        When audit_log is empty, the first inserted entry must have
        previous_hash equal to the genesis hash.
        """
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value='{"id": 1}'
        )
        rows = fetch_audit_rows(cursor)
        assert rows[0]['previous_hash'] == GENESIS_HASH, (
            f"First entry previous_hash should be genesis hash.\n"
            f"  Expected: {GENESIS_HASH}\n"
            f"  Got:      {rows[0]['previous_hash']}"
        )

    def test_first_entry_previous_hash_is_not_null(self, cursor, conn):
        """The first entry's previous_hash must never be NULL."""
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value='{"id": 1}'
        )
        rows = fetch_audit_rows(cursor)
        assert rows[0]['previous_hash'] is not None, (
            "First entry previous_hash is NULL — genesis hash was not applied."
        )

    def test_first_entry_current_hash_is_not_null(self, cursor, conn):
        """The first entry's current_hash must be a non-null 64-char hex string."""
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value='{"id": 1}'
        )
        rows = fetch_audit_rows(cursor)
        h = rows[0]['current_hash']
        assert h is not None, "First entry current_hash is NULL."
        assert len(h) == 64, f"current_hash should be 64 chars, got {len(h)}."

# SECTION 4 — Hash Correctness (Python vs PostgreSQL)
class TestHashCorrectness:

    def test_current_hash_matches_python_recomputation(self, cursor, conn):
        """
        The current_hash stored by PostgreSQL must exactly match
        the hash recomputed by Python using the same formula.
        """
        new_val = '{"id": 1, "first_name": "Alice"}'
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value=new_val
        )
        rows = fetch_audit_rows(cursor)
        row = rows[0]

        expected = compute_expected_hash(
            old_value=row['old_value'],
            new_value=row['new_value'],
            table_name=row['table_name'],
            record_id=row['record_id'],
            operation=row['operation'],
            previous_hash=row['previous_hash']
        )
        assert row['current_hash'] == expected, (
            f"Hash mismatch at log_id {row['log_id']}.\n"
            f"  PostgreSQL stored: {row['current_hash']}\n"
            f"  Python recomputed: {expected}"
        )

    def test_update_entry_hash_matches_python_recomputation(self, cursor, conn):
        """
        An UPDATE audit entry's hash must also match Python recomputation,
        including old_value in the hash input.
        """
        # Entry 1: INSERT
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='I',
            old_value=None,
            new_value='{"id": 1, "first_name": "Alice"}'
        )
        # Entry 2: UPDATE
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=1,
            operation='U',
            old_value='{"id": 1, "first_name": "Alice"}',
            new_value='{"id": 1, "first_name": "Alicia"}'
        )
        rows = fetch_audit_rows(cursor)
        row = rows[1]  

        expected = compute_expected_hash(
            old_value=row['old_value'],
            new_value=row['new_value'],
            table_name=row['table_name'],
            record_id=row['record_id'],
            operation=row['operation'],
            previous_hash=row['previous_hash']
        )
        assert row['current_hash'] == expected, (
            f"UPDATE hash mismatch at log_id {row['log_id']}.\n"
            f"  PostgreSQL stored: {row['current_hash']}\n"
            f"  Python recomputed: {expected}"
        )

    def test_delete_entry_hash_matches_python_recomputation(self, cursor, conn):
        """
        A DELETE audit entry's hash (with new_value=None) must also
        match Python recomputation.
        """
        call_insert_audit_log(
            cursor, conn,
            table_name='patients',
            record_id=5,
            operation='D',
            old_value='{"id": 5, "first_name": "Bob"}',
            new_value=None
        )
        rows = fetch_audit_rows(cursor)
        row = rows[0]

        expected = compute_expected_hash(
            old_value=row['old_value'],
            new_value=row['new_value'],
            table_name=row['table_name'],
            record_id=row['record_id'],
            operation=row['operation'],
            previous_hash=row['previous_hash']
        )
        assert row['current_hash'] == expected, (
            f"DELETE hash mismatch at log_id {row['log_id']}.\n"
            f"  PostgreSQL stored: {row['current_hash']}\n"
            f"  Python recomputed: {expected}"
        )

# SECTION 5 — Chain Integrity (N → N+1 Linking)
class TestChainIntegrity:

    def _insert_n_entries(self, cursor, conn, n):
        """Insert n audit entries and return all rows."""
        for i in range(1, n + 1):
            call_insert_audit_log(
                cursor, conn,
                table_name='patients',
                record_id=i,
                operation='I',
                old_value=None,
                new_value=f'{{"id": {i}}}'
            )
        return fetch_audit_rows(cursor)

    def test_second_entry_previous_hash_equals_first_current_hash(self, cursor, conn):
        """
        Entry 2's previous_hash must exactly equal Entry 1's current_hash.
        This is the fundamental hash-chain link.
        """
        rows = self._insert_n_entries(cursor, conn, 2)
        assert rows[1]['previous_hash'] == rows[0]['current_hash'], (
            "Chain broken between entry 1 and 2.\n"
            f"  Entry 1 current_hash:  {rows[0]['current_hash']}\n"
            f"  Entry 2 previous_hash: {rows[1]['previous_hash']}"
        )

    def test_chain_links_across_five_entries(self, cursor, conn):
        """
        Every consecutive pair in a 5-entry chain must be correctly linked:
        row[i].previous_hash == row[i-1].current_hash
        """
        rows = self._insert_n_entries(cursor, conn, 5)
        for i in range(1, len(rows)):
            assert rows[i]['previous_hash'] == rows[i - 1]['current_hash'], (
                f"Chain broken between log_id {rows[i-1]['log_id']} "
                f"and {rows[i]['log_id']}.\n"
                f"  Expected previous_hash: {rows[i-1]['current_hash']}\n"
                f"  Actual   previous_hash: {rows[i]['previous_hash']}"
            )

    def test_chain_links_across_twenty_entries(self, cursor, conn):
        """
        Stress test: chain must remain intact across 20 consecutive entries
        covering INSERT, UPDATE, and DELETE operations.
        """
        operations = [
            ('I', None, '{"id": 1}'),
            ('U', '{"id": 1}', '{"id": 1, "name": "Updated"}'),
            ('D', '{"id": 1}', None),
        ]
        for i in range(20):
            op, old_val, new_val = operations[i % 3]
            call_insert_audit_log(
                cursor, conn,
                table_name='prescriptions',
                record_id=i + 1,
                operation=op,
                old_value=old_val,
                new_value=new_val
            )
        rows = fetch_audit_rows(cursor)
        assert len(rows) == 20, f"Expected 20 rows, found {len(rows)}."

        for i in range(1, len(rows)):
            assert rows[i]['previous_hash'] == rows[i - 1]['current_hash'], (
                f"Chain broken at log_id {rows[i]['log_id']} "
                f"(entry {i + 1} of 20)."
            )

    def test_all_hashes_recompute_correctly_across_chain(self, cursor, conn):
        """
        For every row in the chain, recompute the hash in Python and confirm
        it matches the stored current_hash. This validates both linking AND
        hash formula correctness end-to-end.
        """
        rows = self._insert_n_entries(cursor, conn, 10)

        expected_prev = GENESIS_HASH
        for row in rows:
            # Check previous_hash links correctly
            assert row['previous_hash'] == expected_prev, (
                f"previous_hash mismatch at log_id {row['log_id']}."
            )
            # Recompute current_hash
            expected_current = compute_expected_hash(
                old_value=row['old_value'],
                new_value=row['new_value'],
                table_name=row['table_name'],
                record_id=row['record_id'],
                operation=row['operation'],
                previous_hash=row['previous_hash']
            )
            assert row['current_hash'] == expected_current, (
                f"current_hash mismatch at log_id {row['log_id']}.\n"
                f"  Stored:   {row['current_hash']}\n"
                f"  Expected: {expected_current}"
            )
            expected_prev = row['current_hash']

# SECTION 6 — Hash Uniqueness
class TestHashUniqueness:

    def test_no_duplicate_current_hashes(self, cursor, conn):
        """
        Every entry in the audit log must have a unique current_hash.
        Duplicate hashes would break the chain's tamper-evidence guarantee.
        """
        for i in range(1, 6):
            call_insert_audit_log(
                cursor, conn,
                table_name='patients',
                record_id=i,
                operation='I',
                old_value=None,
                new_value=f'{{"id": {i}}}'
            )
        rows = fetch_audit_rows(cursor)
        hashes = [row['current_hash'] for row in rows]
        assert len(hashes) == len(set(hashes)), (
            "Duplicate current_hash values found in audit_log. "
            "Each entry must produce a unique hash."
        )

    def test_identical_data_different_position_produces_different_hash(self, cursor, conn):
        """
        Two entries with identical payload but at different positions in the
        chain must produce different current_hashes because their previous_hash
        values differ.
        """
        payload = '{"id": 1, "first_name": "Same"}'
        call_insert_audit_log(
            cursor, conn,
            table_name='patients', record_id=1, operation='I',
            old_value=None, new_value=payload
        )
        call_insert_audit_log(
            cursor, conn,
            table_name='patients', record_id=1, operation='I',
            old_value=None, new_value=payload
        )
        rows = fetch_audit_rows(cursor)
        assert rows[0]['current_hash'] != rows[1]['current_hash'], (
            "Two entries with identical data produced the same hash. "
            "The chain's previous_hash must make each hash unique."
        )