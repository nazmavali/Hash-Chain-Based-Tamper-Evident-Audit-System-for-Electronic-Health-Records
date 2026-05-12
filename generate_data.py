import psycopg2
from faker import Faker
import random
from datetime import datetime, timedelta
import sys

class HealthcareDataGenerator:
    def __init__(self, db_params=None):
        """Initialize the data generator with database connection parameters"""
        self.db_params = db_params or {
            'host': 'localhost',
            'database': 'healthcare_db',
            'user': 'postgres',
            'password': '36375213', 
            'port': '5432'
        }
        
        # Initialize Faker
        self.fake = Faker()
        random.seed(42)  
        Faker.seed(42)
        
        # Medical data constants
        self.blood_types = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']
        self.medications = [
            # Format: (name, common dosages, frequencies)
            ('Lisinopril', ['5mg', '10mg', '20mg', '40mg'], ['Once daily']),
            ('Metformin', ['500mg', '850mg', '1000mg'], ['Twice daily', 'Three times daily']),
            ('Atorvastatin', ['10mg', '20mg', '40mg', '80mg'], ['Once daily']),
            ('Levothyroxine', ['25mcg', '50mcg', '75mcg', '100mcg'], ['Once daily']),
            ('Amlodipine', ['2.5mg', '5mg', '10mg'], ['Once daily']),
            ('Metoprolol', ['25mg', '50mg', '100mg'], ['Twice daily']),
            ('Omeprazole', ['20mg', '40mg'], ['Once daily']),
            ('Losartan', ['25mg', '50mg', '100mg'], ['Once daily']),
            ('Sertraline', ['25mg', '50mg', '100mg'], ['Once daily']),
            ('Simvastatin', ['10mg', '20mg', '40mg'], ['Once daily']),
            ('Albuterol', ['90mcg', '180mcg'], ['As needed']),
            ('Warfarin', ['1mg', '2mg', '5mg'], ['Once daily']),
            ('Gabapentin', ['100mg', '300mg', '600mg'], ['Three times daily']),
            ('Hydrochlorothiazide', ['12.5mg', '25mg'], ['Once daily']),
            ('Furosemide', ['20mg', '40mg', '80mg'], ['Once daily']),
            ('Insulin Glargine', ['100 units/mL'], ['Once daily']),
            ('Amoxicillin', ['250mg', '500mg'], ['Three times daily']),
            ('Prednisone', ['5mg', '10mg', '20mg'], ['Once daily', 'Twice daily']),
            ('Tramadol', ['50mg', '100mg'], ['Every 6 hours as needed']),
            ('Citalopram', ['10mg', '20mg', '40mg'], ['Once daily'])
        ]
        
        self.prescription_statuses = ['Active', 'Completed', 'Cancelled', 'On Hold', 'Discontinued']
    
    def connect_db(self):
        """Establish database connection"""
        try:
            conn = psycopg2.connect(**self.db_params)
            return conn
        except Exception as e:
            print(f"Database connection failed: {e}")
            print("Please check your database parameters:")
            print(f"  Host: {self.db_params['host']}")
            print(f"  Database: {self.db_params['database']}")
            print(f"  User: {self.db_params['user']}")
            return None
    
    def create_tables(self, conn):
        """Create the Patients and Prescriptions tables if they don't exist"""
        cursor = conn.cursor()
        
        try:
            with open('schema.sql', 'r') as f:
                schema_sql = f.read()
            cursor.execute(schema_sql)
            conn.commit()
            print("Database tables created successfully")
        except FileNotFoundError:
            print("schema.sql not found. Creating tables directly...")
            
            cursor.execute("""
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
            """)
            
            cursor.execute("""
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
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_patient_id ON prescriptions(patient_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_status ON prescriptions(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_last_name ON patients(last_name);")
            
            conn.commit()
            print("Database tables created successfully")
        
        cursor.close()
    
    def generate_patient(self):
        """Generate a single patient record"""
        gender = random.choice(['M', 'F'])
        first_name = self.fake.first_name_male() if gender == 'M' else self.fake.first_name_female()
        
        return {
            'first_name': first_name,
            'last_name': self.fake.last_name(),
            'date_of_birth': self.fake.date_of_birth(minimum_age=1, maximum_age=90),
            'gender': gender,
            'email': self.fake.email(),
            'phone': self.fake.phone_number()[:20],
            'address': self.fake.address().replace("\n", ", "),
            'blood_type': random.choice(self.blood_types)
        }
    
    def generate_prescription(self, patient_id):
        """Generate a single prescription record for a given patient"""
        medication = random.choice(self.medications)
        med_name, dosages, frequencies = medication
        
        start_date = self.fake.date_between(start_date='-2y', end_date='today')
        
        # 70% of prescriptions have an end date
        if random.random() < 0.7:
            end_date = self.fake.date_between(start_date=start_date, end_date='+6m')
        else:
            end_date = None
        
        # Random refills (0-5)
        refills = random.randint(0, 5) if random.random() < 0.4 else 0
        
        # Random status
        status = random.choice(self.prescription_statuses)
        
        # Instructions
        instructions = random.choice([
            "Take with food",
            "Take on empty stomach",
            "Take with plenty of water",
            "Avoid alcohol while taking this medication",
            "May cause drowsiness",
            "Take as needed for symptoms",
            "Complete full course even if feeling better",
            ""
        ])
        
        return {
            'patient_id': patient_id,
            'medication_name': med_name,
            'dosage': random.choice(dosages),
            'frequency': random.choice(frequencies),
            'prescribed_date': start_date,
            'end_date': end_date,
            'refills_left': refills,
            'status': status,
            'instructions': instructions
        }
    
    def insert_patients_batch(self, conn, patients_data, batch_size=1000):
        """Insert patients in batches for better performance"""
        cursor = conn.cursor()
        
        total_patients = len(patients_data)
        print(f"Inserting {total_patients} patients in batches of {batch_size}...")
        
        for i in range(0, total_patients, batch_size):
            batch = patients_data[i:i + batch_size]
            values = []
            
            for patient in batch:
                values.append("(%s, %s, %s, %s, %s, %s, %s, %s)" % (
                    conn.cursor().mogrify("'%s'" % patient['first_name'].replace("'", "''")).decode(),
                    conn.cursor().mogrify("'%s'" % patient['last_name'].replace("'", "''")).decode(),
                    "'" + str(patient['date_of_birth']) + "'",
                    "'" + patient['gender'] + "'",
                    conn.cursor().mogrify("'%s'" % patient['email'].replace("'", "''")).decode(),
                    conn.cursor().mogrify("'%s'" % patient['phone'].replace("'", "''")).decode(),
                    conn.cursor().mogrify("'%s'" % patient['address'].replace("'", "''")).decode(),
                    "'" + patient['blood_type'] + "'"
                ))
            
            sql = f"""
            INSERT INTO patients 
            (first_name, last_name, date_of_birth, gender, email, phone, address, blood_type) 
            VALUES {','.join(values)};
            """
            
            cursor.execute(sql)
            conn.commit()
            
            inserted = min(i + batch_size, total_patients)
            if inserted % 5000 == 0 or inserted == total_patients:
                print(f"Inserted {inserted}/{total_patients} patients")
        
        cursor.execute("SELECT MAX(id) FROM patients;")
        last_id = cursor.fetchone()[0]
        
        cursor.close()
        return last_id
    
    def insert_prescriptions_batch(self, conn, prescriptions_data, batch_size=2000):
        """Insert prescriptions in batches for better performance"""
        cursor = conn.cursor()
        
        total_prescriptions = len(prescriptions_data)
        print(f"Inserting {total_prescriptions} prescriptions in batches of {batch_size}...")
        
        for i in range(0, total_prescriptions, batch_size):
            batch = prescriptions_data[i:i + batch_size]
            values = []
            
            for presc in batch:
                end_date_str = "'" + str(presc['end_date']) + "'" if presc['end_date'] else 'NULL'
                
                med_name = presc['medication_name'].replace("'", "''")
                instructions = presc['instructions'].replace("'", "''")
                
                values.append(f"({presc['patient_id']}, '{med_name}', "
                            f"'{presc['dosage']}', '{presc['frequency']}', "
                            f"'{presc['prescribed_date']}', {end_date_str}, "
                            f"{presc['refills_left']}, '{presc['status']}', "
                            f"'{instructions}')")
            
            sql = f"""
            INSERT INTO prescriptions 
            (patient_id, medication_name, dosage, frequency, prescribed_date, 
            end_date, refills_left, status, instructions) 
            VALUES {','.join(values)};
            """
            
            cursor.execute(sql)
            conn.commit()
            
            inserted = min(i + batch_size, total_prescriptions)
            if inserted % 10000 == 0 or inserted == total_prescriptions:
                print(f"Inserted {inserted}/{total_prescriptions} prescriptions")
        
        cursor.close()
    
    def generate_data(self, num_patients=10000, num_prescriptions=50000):
        """Main method to generate and insert all data"""
        print("=" * 60)
        print("HEALTHCARE DATA GENERATOR")
        print("=" * 60)
        
        conn = self.connect_db()
        if not conn:
            sys.exit(1)
        
        try:
            # Step 1: Create tables
            print("\n Step 1: Creating database tables...")
            self.create_tables(conn)
            
            # Step 2: Generate patients data
            print(f"\n Step 2: Generating {num_patients} patient records...")
            patients_data = []
            for i in range(num_patients):
                if i % 2000 == 0:
                    print(f"  Generated {i}/{num_patients} patients...")
                patients_data.append(self.generate_patient())
            
            # Step 3: Insert patients
            last_patient_id = self.insert_patients_batch(conn, patients_data)
            
            # Step 4: Generate prescriptions data
            print(f"\n Step 3: Generating {num_prescriptions} prescription records...")
            prescriptions_data = []
            
            # Get patient IDs for prescription assignment
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM patients ORDER BY id;")
            patient_ids = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            if not patient_ids:
                print("No patients found. Cannot generate prescriptions.")
                return
            
            # Generate prescriptions
            for i in range(num_prescriptions):
                if i % 10000 == 0:
                    print(f"  Generated {i}/{num_prescriptions} prescriptions...")
                
                # Randomly assign to a patient
                patient_id = random.choice(patient_ids)
                prescriptions_data.append(self.generate_prescription(patient_id))
            
            # Step 5: Insert prescriptions
            self.insert_prescriptions_batch(conn, prescriptions_data)
            
            # Step 6: Display statistics
            print("\n Step 4: Generating statistics...")
            self.display_statistics(conn)
            
            print("\n" + "=" * 60)
            print(" DATA GENERATION COMPLETE!")
            print("=" * 60)
            
        except Exception as e:
            print(f" Error during data generation: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
            print("\nDatabase connection closed.")
    
    def display_statistics(self, conn):
        """Display statistics about the generated data"""
        cursor = conn.cursor()
        
        # Count patients
        cursor.execute("SELECT COUNT(*) FROM patients;")
        patient_count = cursor.fetchone()[0]
        
        # Count prescriptions
        cursor.execute("SELECT COUNT(*) FROM prescriptions;")
        prescription_count = cursor.fetchone()[0]
        
        # Average prescriptions per patient
        cursor.execute("""
            SELECT AVG(prescription_count) 
            FROM (
                SELECT patient_id, COUNT(*) as prescription_count 
                FROM prescriptions 
                GROUP BY patient_id
            ) AS counts;
        """)
        avg_per_patient = cursor.fetchone()[0]
        
        # Prescriptions by status
        cursor.execute("""
            SELECT status, COUNT(*) 
            FROM prescriptions 
            GROUP BY status 
            ORDER BY COUNT(*) DESC;
        """)
        status_counts = cursor.fetchall()
        
        # Top prescribed medications
        cursor.execute("""
            SELECT medication_name, COUNT(*) as count 
            FROM prescriptions 
            GROUP BY medication_name 
            ORDER BY count DESC 
            LIMIT 10;
        """)
        top_meds = cursor.fetchall()
        
        print(f"\n DATABASE STATISTICS:")
        print(f"   Patients: {patient_count:,}")
        print(f"   Prescriptions: {prescription_count:,}")
        print(f"   Avg prescriptions per patient: {avg_per_patient:.1f}")
        
        print(f"\n   Prescription Status Distribution:")
        for status, count in status_counts:
            percentage = (count / prescription_count) * 100
            print(f"     {status}: {count:,} ({percentage:.1f}%)")
        
        print(f"\n   Top 10 Medications:")
        for i, (med, count) in enumerate(top_meds, 1):
            print(f"     {i}. {med}: {count:,}")
        
        cursor.close()


def main():
    """Main function to run the data generator"""
    db_params = {
        'host': 'localhost',
        'database': 'healthcare_db',
        'user': 'postgres',
        'password': '36375213', 
        'port': '5432'
    }
    
    generator = HealthcareDataGenerator(db_params)
    
    generator.generate_data(
        num_patients=10000,
        num_prescriptions=50000
    )


if __name__ == "__main__":
    main()