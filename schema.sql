-- PART A. Data and Project Setup

-- Create database and tables

-- CREATE DATABASE healthcare_db;

-- Connect to healthcare_db:

-- Create tables

-- Patients table
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender CHAR(1) CHECK (gender IN ('M', 'F', 'O')),
    email VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    blood_type VARCHAR(3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prescriptions table
CREATE TABLE IF NOT EXISTS prescriptions (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    medication_name VARCHAR(100) NOT NULL,
    dosage VARCHAR(50) NOT NULL,
    frequency VARCHAR(50) NOT NULL,
    prescribed_date DATE NOT NULL,
    end_date DATE,
    refills_left INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'Active',
    instructions TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prescriptions_patient_id ON prescriptions(patient_id);
CREATE INDEX IF NOT EXISTS idx_prescriptions_status ON prescriptions(status);
CREATE INDEX IF NOT EXISTS idx_patients_last_name ON patients(last_name);

-- Show 10 records from patients table
SELECT * FROM patients LIMIT 10;

-- Show 10 records from prescriptions table
SELECT * FROM prescriptions LIMIT 10;

-- PART B. Implementing the Hash-Chain Based Tamper-Evident Log

-- B.1. Audit Log Table (Hash-Chain Based Tamper-Evident Log)

CREATE TABLE IF NOT EXISTS audit_log (
    log_id SERIAL PRIMARY KEY,

    -- What was changed
    table_name VARCHAR(50) NOT NULL,        -- e.g., 'patients', 'prescriptions'
    record_id INTEGER NOT NULL,              -- ID of the affected row
    operation CHAR(1) NOT NULL CHECK (operation IN ('I', 'U', 'D')),
                                              -- I = INSERT, U = UPDATE, D = DELETE

    -- Before and after values
    old_value JSONB,                         -- NULL for INSERT
    new_value JSONB,                         -- NULL for DELETE

    -- Metadata
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(100) DEFAULT current_user,

    -- Hash-chain fields
    previous_hash CHAR(64),                  -- SHA-256 hash of previous log entry
    current_hash CHAR(64) NOT NULL            -- SHA-256 hash of this log entry
);

-- Indexes for performance and ordered verification
CREATE INDEX IF NOT EXISTS idx_audit_log_table_record
    ON audit_log (table_name, record_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_changed_at
    ON audit_log (changed_at);

CREATE INDEX IF NOT EXISTS idx_audit_log_chain
    ON audit_log (log_id);

-- B.2. Enable hashing support in PostgreSQL

-- (SHA-256)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Genesis hash for the audit hash-chain
-- Used when there is no previous audit log entry
CREATE OR REPLACE VIEW audit_genesis_hash AS
SELECT encode(digest('GENESIS', 'sha256'), 'hex') AS hash;

-- B.3. Hash-chain audit insert function

CREATE OR REPLACE FUNCTION insert_audit_log(
    p_table_name VARCHAR,
    p_record_id INTEGER,
    p_operation CHAR(1),
    p_old_value JSONB,
    p_new_value JSONB
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_previous_hash CHAR(64);
    v_current_hash  CHAR(64);
BEGIN
    -- Get previous hash or genesis hash for first entry
    SELECT current_hash
    INTO v_previous_hash
    FROM audit_log
    ORDER BY log_id DESC
    LIMIT 1;

    IF v_previous_hash IS NULL THEN
        SELECT hash
        INTO v_previous_hash
        FROM audit_genesis_hash;
    END IF;

    -- Compute current hash
    v_current_hash :=
        encode(
            digest(
                COALESCE(p_old_value::text, '') ||
                COALESCE(p_new_value::text, '') ||
                p_table_name ||
                p_record_id::text ||
                p_operation ||
                v_previous_hash,
                'sha256'
            ),
            'hex'
        );

    -- Insert audit log entry
    INSERT INTO audit_log (
        table_name,
        record_id,
        operation,
        old_value,
        new_value,
        previous_hash,
        current_hash
    )
    VALUES (
        p_table_name,
        p_record_id,
        p_operation,
        p_old_value,
        p_new_value,
        v_previous_hash,
        v_current_hash
    );
END;
$$;

-- B.4. Create triggers on Patients and Prescriptions

-- Trigger function for auditing changes
CREATE OR REPLACE FUNCTION audit_trigger_fn()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM insert_audit_log(
            TG_TABLE_NAME::varchar,
            NEW.id,
            'I'::char(1),
            NULL::jsonb,
            to_jsonb(NEW)
        );
        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        PERFORM insert_audit_log(
            TG_TABLE_NAME::varchar,
            NEW.id,
            'U'::char(1),
            to_jsonb(OLD),
            to_jsonb(NEW)
        );
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        PERFORM insert_audit_log(
            TG_TABLE_NAME::varchar,
            OLD.id,
            'D'::char(1),
            to_jsonb(OLD),
            NULL::jsonb
        );
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$;

-- Triggers for patients table
CREATE TRIGGER patients_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON patients
FOR EACH ROW
EXECUTE FUNCTION audit_trigger_fn();


-- Triggers for prescriptions table
CREATE TRIGGER prescriptions_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON prescriptions
FOR EACH ROW
EXECUTE FUNCTION audit_trigger_fn();

-- B.5. Performing Tampering Experiments as Proof
-- Confirm audit log does not exist before trigger

SELECT log_id, table_name, operation, current_hash
FROM audit_log
ORDER BY log_id
LIMIT 5;

-- Part 1: INSERT Demo
-- INSERT a patient to trigger and audit logging

INSERT INTO patients (first_name, last_name, date_of_birth, gender)
VALUES ('John', 'Doe', '1980-01-01', 'M');

-- Confirm audit log exists
SELECT log_id, table_name, operation
FROM audit_log;

-- Tamper and detect
-- a)	Which audit rows exist
SELECT log_id, table_name, operation, current_hash
FROM audit_log
ORDER BY log_id;

-- b)	Tampering attack: Modifying the existing audit record
UPDATE audit_log
SET old_value = '{"tampered": true}'
WHERE log_id = 1;


-- Part 2:UPDATE Demo
-- Inserting a Clean Patient 
INSERT INTO patients (first_name, last_name, date_of_birth, gender)
VALUES ('Jane', 'Chesky', '2005-01-01', 'F');

-- Current State of Patient 
SELECT id, first_name, last_name, date_of_birth, gender
FROM patients
WHERE id = 2;

-- Performing UPDATE to Patient FirstName as Proof
UPDATE patients
SET first_name = 'Olivia'
WHERE id = 2;

-- Confirmation of Successful UPDATE
SELECT id, first_name, last_name, date_of_birth, gender
FROM patients
WHERE id = 2;

-- Audit log proof:
-- old_value contains the original row (first_name = 'Jane')
-- new_value contains the updated row (first_name = 'Olivia')
SELECT
    log_id,
    operation,
    old_value,
    new_value
FROM audit_log
WHERE record_id = 2
  AND table_name = 'patients'
  AND operation = 'U';


-- Part 3: DELETE Demo
-- Confirming the Patient Still Exists Before Performing Deletion Test 
SELECT id, first_name, last_name, date_of_birth, gender
FROM patients
WHERE id = 2;

-- Performing the DELETE Process
DELETE FROM patients
WHERE id = 2;

-- Confirming Patient Deletion
SELECT id, first_name, last_name, date_of_birth, gender
FROM patients
WHERE id = 2;

-- Audit log proof:
-- old_value contains the full deleted row
-- new_value is NULL (nothing exists after deletion)
-- This proves the audit log preserves the deleted data
-- even though the patient row no longer exists in the table
SELECT
    log_id,
    operation,
    old_value,
    new_value
FROM audit_log
WHERE record_id = 2
  AND table_name = 'patients'
  AND operation = 'D';
  
-- Part C: Benchmarking
-- C. 1. Benchmarking with Auditing OFF
ALTER TABLE patients DISABLE TRIGGER patients_audit_trigger;
ALTER TABLE prescriptions DISABLE TRIGGER prescriptions_audit_trigger;

-- Check
SELECT tgname, tgenabled
FROM pg_trigger
WHERE tgname IN ('patients_audit_trigger', 'prescriptions_audit_trigger');

-- Drop all data from the patients and prescriptions tables
TRUNCATE TABLE patients RESTART IDENTITY CASCADE;
TRUNCATE TABLE prescriptions RESTART IDENTITY CASCADE;


-- C. 2. Benchmarking with Auditing ON
ALTER TABLE patients ENABLE TRIGGER patients_audit_trigger;
ALTER TABLE prescriptions ENABLE TRIGGER prescriptions_audit_trigger;

-- Check
SELECT tgname, tgenabled
FROM pg_trigger
WHERE tgname IN ('patients_audit_trigger', 'prescriptions_audit_trigger');

-- Drop all data from the patients and prescriptions tables
TRUNCATE TABLE patients RESTART IDENTITY CASCADE;
TRUNCATE TABLE prescriptions RESTART IDENTITY CASCADE;
