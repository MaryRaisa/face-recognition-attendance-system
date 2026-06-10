import cv2
import os
import numpy as np
import json
import time
import sqlite3
from datetime import datetime

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def init_db_if_needed(db_path):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL
    )
    ''')
    conn.commit()
    conn.close()

def get_images_and_labels(dataset_dir, db_path):
    init_db_if_needed(db_path)
    
    # Get all subdirectories in dataset/
    subdirs = [d for d in os.listdir(dataset_dir) if os.path.isdir(os.path.join(dataset_dir, d))]
    
    face_samples = []
    ids = []
    users_map = {}
    
    # Sort subdirectories to ensure consistent ID assignment
    subdirs.sort()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    for folder_name in subdirs:
        student_dir = os.path.join(dataset_dir, folder_name)
        student_name = folder_name.replace("_", " ")
        
        # Check if student exists in database
        cursor.execute("SELECT id FROM students WHERE name = ?", (student_name,))
        row = cursor.fetchone()
        
        if row:
            label_id = row['id']
        else:
            # Insert new student into DB
            username = student_name.lower().replace(" ", "")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cursor.execute(
                    "INSERT INTO students (name, username, created_at) VALUES (?, ?, ?)",
                    (student_name, username, now_str)
                )
                conn.commit()
                label_id = cursor.lastrowid
                print(f"[+] Added student '{student_name}' to database with ID: {label_id}")
            except sqlite3.IntegrityError:
                username = f"{username}{int(time.time())}"
                cursor.execute(
                    "INSERT INTO students (name, username, created_at) VALUES (?, ?, ?)",
                    (student_name, username, now_str)
                )
                conn.commit()
                label_id = cursor.lastrowid
                print(f"[+] Added student '{student_name}' to database with ID: {label_id}")
                
        users_map[str(label_id)] = student_name
        
        image_paths = [os.path.join(student_dir, f) for f in os.listdir(student_dir) if f.endswith((".jpg", ".jpeg"))]
        
        for image_path in image_paths:
            try:
                gray_img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if gray_img is None:
                    continue
                face_samples.append(gray_img)
                ids.append(label_id)
            except Exception as e:
                print(f"[-] Error loading image {image_path}: {e}")
                
    conn.close()
    return face_samples, ids, users_map

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "dataset")
    trainer_dir = os.path.join(base_dir, "trainer")
    trainer_file = os.path.join(trainer_dir, "trainer.yml")
    users_file = os.path.join(dataset_dir, "users.json")
    db_path = os.path.join(base_dir, "attendance", "database.db")
    
    os.makedirs(trainer_dir, exist_ok=True)
    
    clear_console()
    print("=" * 50)
    print("   FACE RECOGNITION ATTENDANCE SYSTEM - TRAINING")
    print("=" * 50)
    
    if not os.path.exists(dataset_dir) or len(os.listdir(dataset_dir)) == 0:
        print("\n[-] Error: Dataset directory is empty or does not exist.")
        print("[*] Please run 'register.py' first to register students.")
        input("\nPress Enter to exit...")
        return
        
    print("\n[*] Loading face samples from student dataset subdirectories...")
    start_time = time.time()
    
    face_samples, ids, users_map = get_images_and_labels(dataset_dir, db_path)
    
    if len(face_samples) == 0:
        print("\n[-] Error: No valid face samples found in any subdirectories.")
        print("[*] Ensure samples are saved under dataset/<student_name>/ as .jpg files.")
        input("\nPress Enter to exit...")
        return
        
    num_samples = len(face_samples)
    unique_ids = len(users_map)
    
    print(f"[+] Loaded {num_samples} samples belonging to {unique_ids} registered students.")
    print("[*] Training the LBPH Recognizer...")
    
    try:
        # Save mapping to users.json for recognizer use (as backup)
        with open(users_file, 'w') as f:
            json.dump(users_map, f, indent=4)
            
        # Initialize LBPH Face Recognizer
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        
        # Train on samples and labels
        recognizer.train(face_samples, np.array(ids))
        
        # Write training to trainer.yml
        recognizer.write(trainer_file)
        
        elapsed_time = time.time() - start_time
        
        print("\n" + "=" * 50)
        print("   TRAINING SUMMARY")
        print("=" * 50)
        print(f"[+] Status: SUCCESS")
        print(f"[+] Distinct Students Trained: {unique_ids}")
        print(f"[+] Total Samples Processed: {num_samples}")
        print(f"[+] Output Model: {os.path.relpath(trainer_file, base_dir)}")
        print(f"[+] User database updated at: {os.path.relpath(users_file, base_dir)}")
        print(f"[+] Training Time: {elapsed_time:.2f} seconds")
        print("=" * 50)
        
        print("\nTrained Students List:")
        for uid, name in users_map.items():
            print(f" - ID {uid}: {name}")
                
    except AttributeError:
        print("\n[-] Error: OpenCV face recognition module not available.")
        print("[*] Make sure 'opencv-contrib-python' is installed.")
    except Exception as e:
        print(f"\n[-] Error occurred during training: {e}")
        
    input("\nPress Enter to return to terminal...")

if __name__ == "__main__":
    main()
