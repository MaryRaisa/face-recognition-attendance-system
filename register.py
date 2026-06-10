import cv2
import os
import time
import sqlite3
from datetime import datetime

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_student_name():
    print("=" * 50)
    print("   FACE RECOGNITION ATTENDANCE SYSTEM - REGISTER")
    print("=" * 50)
    
    while True:
        student_name = input("\nEnter Student Name: ").strip()
        if not student_name:
            print("[-] Name cannot be empty.")
            continue
        if "," in student_name:
            print("[-] Name cannot contain commas.")
            continue
        
        # Check for invalid directory characters on Windows/Linux
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        has_invalid = False
        for char in invalid_chars:
            if char in student_name:
                print(f"[-] Name cannot contain special characters: {char}")
                has_invalid = True
                break
        if has_invalid:
            continue
            
        break
    return student_name

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "dataset")
    db_path = os.path.join(base_dir, "attendance", "database.db")
    os.makedirs(dataset_dir, exist_ok=True)
    
    clear_console()
    student_name = get_student_name()
    
    # Store images directly in dataset/student_name/
    student_dir = os.path.join(dataset_dir, student_name)
    
    # Check if student is already registered
    if os.path.exists(student_dir):
        print(f"[!] Warning: A folder for student '{student_name}' already exists.")
        choice = input("Overwrite existing face samples? (y/n): ").strip().lower()
        if choice != 'y':
            print("[*] Aborting registration.")
            return
    else:
        os.makedirs(student_dir, exist_ok=True)

    # Sync with SQLite database
    try:
        db_dir = os.path.dirname(db_path)
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
        cursor.execute("SELECT id FROM students WHERE name = ?", (student_name,))
        row = cursor.fetchone()
        if not row:
            username = student_name.lower().replace(" ", "")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cursor.execute(
                    "INSERT INTO students (name, username, created_at) VALUES (?, ?, ?)",
                    (student_name, username, now_str)
                )
                conn.commit()
                print(f"[+] Registered student '{student_name}' in SQLite database.")
            except sqlite3.IntegrityError:
                username = f"{username}{int(time.time())}"
                cursor.execute(
                    "INSERT INTO students (name, username, created_at) VALUES (?, ?, ?)",
                    (student_name, username, now_str)
                )
                conn.commit()
                print(f"[+] Registered student '{student_name}' with unique username '{username}' in SQLite database.")
        else:
            print(f"[*] Student '{student_name}' is already present in SQLite database.")
        conn.close()
    except Exception as e:
        print(f"[!] Warning: Could not sync with SQLite database: {e}")
        
    # Initialize Cascade Classifier
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        print("[-] Error: Could not load Haar Cascade Face Classifier.")
        return
 
    # Start webcam capture
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[-] Error: Could not access the webcam.")
        print("[*] Please check if the camera is connected and not in use by another program.")
        input("\nPress Enter to exit...")
        return
    
    target_samples = 100
    count = 0
    capturing = False
    
    print("\n" + "=" * 50)
    print("   WEBCAM CAPTURE CONTROL")
    print("=" * 50)
    print("1. A window named 'Register Student Face' will open.")
    print("2. Look directly at the camera.")
    print("3. Press 'SPACE' to START capturing samples.")
    print("4. Move your head slightly for better accuracy.")
    print("5. Press 'q' at any time to ABORT/QUIT.")
    print("=" * 50)
    print("\nLaunching webcam...")
    time.sleep(1)
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[-] Error: Failed to grab frame.")
            break
            
        # Flip frame horizontally for mirror view
        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = face_cascade.detectMultiScale(
            gray, 
            scaleFactor=1.2, 
            minNeighbors=5, 
            minSize=(100, 100)
        )
        
        h_frame, w_frame, _ = frame.shape
        
        # Overlay instruction bar
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w_frame, 60), (40, 40, 40), -1)
        
        if not capturing:
            cv2.putText(overlay, "Press SPACE to Start Capturing", (20, 38), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        else:
            cv2.putText(overlay, f"Capturing: {count}/{target_samples} images", (20, 38), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
            
        cv2.putText(overlay, "Press 'q' to Quit", (w_frame - 180, 38), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        
        cv2.addWeighted(overlay, 0.8, frame, 0.2, 0, frame)
        
        num_faces = len(faces)
        
        if num_faces == 0:
            if capturing:
                cv2.putText(frame, "No Face Detected", (20, h_frame - 20), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        elif num_faces > 1:
            cv2.putText(frame, "Warning: Multiple Faces Detected!", (20, h_frame - 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
        else:
            x, y, w, h = faces[0]
            box_color = (0, 255, 0) if capturing else (255, 120, 0)
            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
            cv2.putText(frame, student_name, (x, y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2, cv2.LINE_AA)
            
            if capturing:
                count += 1
                # Crop and resize face
                face_crop = gray[y:y+h, x:x+w]
                if face_crop.size > 0:
                    face_resized = cv2.resize(face_crop, (200, 200), interpolation=cv2.INTER_AREA)
                    
                    # Save the sample into the student_name subfolder
                    sample_filename = os.path.join(student_dir, f"{count}.jpg")
                    cv2.imwrite(sample_filename, face_resized)
                
                # Flash effect
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 4)
                time.sleep(0.05)
                
        cv2.imshow("Register Student Face", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):  # SPACE bar
            if num_faces == 1:
                capturing = True
                print("[+] Face capture started...")
            else:
                print("[-] Ensure exactly ONE face is visible to start capture.")
        elif key == ord('q'):
            print("[!] Capture aborted by user.")
            break
            
        if count >= target_samples:
            print(f"[+] Successfully registered '{student_name}'.")
            print(f"[+] Saved {target_samples} samples to dataset/{student_name}/")
            break
            
    cap.release()
    cv2.destroyAllWindows()
    input("\nPress Enter to return to terminal...")

if __name__ == "__main__":
    main()
