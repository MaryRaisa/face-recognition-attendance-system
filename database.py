import os
import sqlite3
import csv
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

def get_db_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path):
    # Ensure database directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        roll_number TEXT UNIQUE,
        department TEXT,
        year TEXT,
        created_at TEXT NOT NULL
    )
    ''')
    
    # Migration checks for students table
    cursor.execute("PRAGMA table_info(students)")
    columns = [col[1] for col in cursor.fetchall()]
    if "roll_number" not in columns:
        try:
            cursor.execute("ALTER TABLE students ADD COLUMN roll_number TEXT UNIQUE")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE students ADD COLUMN roll_number TEXT")
    if "department" not in columns:
        cursor.execute("ALTER TABLE students ADD COLUMN department TEXT")
    if "year" not in columns:
        cursor.execute("ALTER TABLE students ADD COLUMN year TEXT")
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        confidence REAL NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS login_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )
    ''')
    
    # Check if admins table is empty, seed a default admin
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        default_admin_user = "admin"
        default_admin_pass = "admin123"
        hashed = generate_password_hash(default_admin_pass)
        cursor.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", (default_admin_user, hashed))
        print(f"[+] Default admin seeded (Username: {default_admin_user}, Password: {default_admin_pass})")
        
    conn.commit()
    conn.close()

# Admin CRUD
def check_admin_login(db_path, username, password):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM admins WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row and check_password_hash(row['password_hash'], password):
        return True
    return False

def add_admin(db_path, username, password):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    hashed = generate_password_hash(password)
    try:
        cursor.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", (username, hashed))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

# Student CRUD
def add_student(db_path, name, username, roll_number=None, department=None, year=None):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    student_id = None
    try:
        cursor.execute(
            "INSERT INTO students (name, username, roll_number, department, year, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, username, roll_number, department, year, now_str)
        )
        conn.commit()
        student_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return student_id

def get_student_by_id(db_path, student_id):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_student_by_username(db_path, username):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_students(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_student(db_path, student_id):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
    # Since Cascade isn't always active in SQLite without PRAGMA, let's delete attendance manually too
    cursor.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()

# Attendance operations
def is_attendance_marked_today(db_path, student_id):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT COUNT(*) FROM attendance WHERE student_id = ? AND date = ?",
        (student_id, today)
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def mark_attendance_in_db_and_csv(db_path, student_id, confidence, attendance_csv):
    if is_attendance_marked_today(db_path, student_id):
        return False, "Attendance already marked today."
        
    student = get_student_by_id(db_path, student_id)
    if not student:
        return False, "Student does not exist."
        
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")
    
    # Save to SQLite
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO attendance (student_id, date, time, confidence) VALUES (?, ?, ?, ?)",
        (student_id, today, now_time, confidence)
    )
    conn.commit()
    conn.close()
    
    # Save to CSV (sync)
    try:
        csv_dir = os.path.dirname(attendance_csv)
        if csv_dir:
            os.makedirs(csv_dir, exist_ok=True)
            
        file_exists = os.path.exists(attendance_csv)
        with open(attendance_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "ID", "Name", "Time", "ConfidenceDistance"])
            writer.writerow([today, student_id, student['name'], now_time, f"{confidence:.2f}"])
    except Exception as e:
        print(f"[-] Error syncing attendance to CSV: {e}")
        # Note: we still return True since SQLite succeeded
        
    return True, f"Success: Attendance marked for {student['name']}."

def get_all_attendance(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.id, a.student_id, s.name, s.username, s.roll_number, s.department, s.year, a.date, a.time, a.confidence
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        ORDER BY a.date DESC, a.time DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_student_attendance(db_path, student_id):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, date, time, confidence
        FROM attendance
        WHERE student_id = ?
        ORDER BY date DESC, time DESC
    ''', (student_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# Audit/Login History Logging
def add_login_log(db_path, username, role, status):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO login_history (username, role, status, timestamp) VALUES (?, ?, ?, ?)",
        (username, role, status, now_str)
    )
    conn.commit()
    conn.close()

def get_login_history(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM login_history ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_student_login_history(db_path, username):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM login_history WHERE username = ? ORDER BY timestamp DESC",
        (username,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
