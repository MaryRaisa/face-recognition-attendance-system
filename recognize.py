import cv2
import os
import json
import time
import csv
import sqlite3
from datetime import datetime

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def load_users(users_file, db_path):
    # Try to load from SQLite database first
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM students")
            users = {str(row['id']): row['name'] for row in cursor.fetchall()}
            conn.close()
            if users:
                return users
        except Exception as e:
            print(f"[!] Warning: Could not read students from SQLite database: {e}")
            
    # Fallback to users.json
    if not os.path.exists(users_file):
        return {}
    try:
        with open(users_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def load_marked_today(csv_file, db_path):
    marked = set()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Try database first
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT student_id FROM attendance WHERE date = ?", (today,))
            for row in cursor.fetchall():
                marked.add(str(row[0]))
            conn.close()
            return marked
        except Exception as e:
            print(f"[!] Warning: Could not read attendance from SQLite database: {e}")
            
    # Fallback to CSV file
    if not os.path.exists(csv_file):
        return marked
    try:
        with open(csv_file, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header:
                for row in reader:
                    if len(row) >= 2:
                        row_date = row[0].strip()
                        row_id = row[1].strip()
                        if row_date == today:
                            marked.add(row_id)
    except Exception as e:
        print(f"[-] Error reading attendance CSV: {e}")
    return marked

def mark_attendance(user_id, name, confidence_score, csv_file, db_path):
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")
    file_exists = os.path.exists(csv_file)
    
    # Save to SQLite database
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Verify student exists in DB
            cursor.execute("SELECT id FROM students WHERE id = ?", (int(user_id),))
            student_exists = cursor.fetchone()
            if student_exists:
                cursor.execute(
                    "INSERT INTO attendance (student_id, date, time, confidence) VALUES (?, ?, ?, ?)",
                    (int(user_id), today, now_time, confidence_score)
                )
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] Warning: Could not save attendance to SQLite database: {e}")
            
    # Save to CSV
    try:
        with open(csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "ID", "Name", "Time", "ConfidenceDistance"])
            writer.writerow([today, user_id, name, now_time, f"{confidence_score:.2f}"])
        return True
    except Exception as e:
        print(f"[-] Error writing to CSV: {e}")
        return False

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "dataset")
    trainer_file = os.path.join(base_dir, "trainer", "trainer.yml")
    users_file = os.path.join(dataset_dir, "users.json")
    attendance_dir = os.path.join(base_dir, "attendance")
    attendance_csv = os.path.join(attendance_dir, "attendance.csv")
    db_path = os.path.join(attendance_dir, "database.db")
    
    os.makedirs(attendance_dir, exist_ok=True)
    
    clear_console()
    print("=" * 50)
    print("   FACE RECOGNITION ATTENDANCE SYSTEM - RECOGNIZER")
    print("=" * 50)
    
    # Verify model files and configurations
    if not os.path.exists(trainer_file):
        print(f"[-] Error: Trained model file not found at {trainer_file}")
        print("[*] Please run 'train.py' first to train the recognizer.")
        input("\nPress Enter to exit...")
        return
        
    users = load_users(users_file, db_path)
    if not users:
        print("[-] Error: User database mappings not found or empty.")
        print("[*] Please run 'register.py' first to register users.")
        input("\nPress Enter to exit...")
        return
        
    # Initialize LBPH Recognizer and load trained XML
    try:
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.read(trainer_file)
    except AttributeError:
        print("\n[-] Error: OpenCV face recognition module not available.")
        print("[*] Make sure 'opencv-contrib-python' is installed (not just standard 'opencv-python').")
        input("\nPress Enter to exit...")
        return
    except Exception as e:
        print(f"[-] Error loading trainer file: {e}")
        input("\nPress Enter to exit...")
        return

    # Load face cascade
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        print("[-] Error: Could not load Haar Cascade Face Classifier.")
        return
        
    # Start Video Capture
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[-] Error: Could not access the webcam.")
        input("\nPress Enter to exit...")
        return
        
    print("\n[*] Initializing Face Recognition...")
    print("[*] Press 'q' to exit the camera screen.")
    print("[*] Press 'r' to reload users list and reset duplicate check.")
    print("=" * 50)
    
    # LBPH Confidence settings (LBPH returns distance - lower values represent closer match)
    # Threshold for recognizing the person
    CONFIDENCE_THRESHOLD = 55.0 
    
    # Load already marked attendance for today to prevent duplicates
    marked_today = load_marked_today(attendance_csv, db_path)
    if marked_today:
        print(f"[*] Loaded {len(marked_today)} users who already marked attendance today.")
    
    # Visual notification tracker
    # Format: {"name": str, "time": str, "expires": float_timestamp}
    last_logged_notification = None
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[-] Error: Failed to grab frame.")
            break
            
        # Flip frame horizontally for natural mirror feel
        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(80, 80)
        )
        
        current_time = time.time()
        
        # Render bottom info bar background
        h_frame, w_frame, _ = frame.shape
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h_frame - 40), (w_frame, h_frame), (30, 30, 30), -1)
        cv2.putText(overlay, "System Active | Press 'q' to Quit | 'r' to Reload", (15, h_frame - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.8, frame, 0.2, 0, frame)
        
        # Draw bounding boxes and run predictions
        for (x, y, w, h) in faces:
            # Crop gray face region
            face_gray = gray[y:y+h, x:x+w]
            face_gray_resized = cv2.resize(face_gray, (200, 200), interpolation=cv2.INTER_AREA)
            
            # Predict
            label_id, confidence_dist = recognizer.predict(face_gray_resized)
            label_id_str = str(label_id)
            
            # Calculate match percentage (for visual display, distance of 0 is 100%)
            # We scale from [0, 100] distance to [100%, 0%] match percentage
            match_percentage = max(0, min(100, int(100 - confidence_dist)))
            
            # Check if prediction distance is within acceptable confidence threshold
            if confidence_dist < CONFIDENCE_THRESHOLD and label_id_str in users:
                user_name = users[label_id_str]
                box_color = (0, 255, 0)  # Green for recognized
                
                # Check duplicate attendance on the same day
                if label_id_str not in marked_today:
                    success = mark_attendance(label_id_str, user_name, confidence_dist, attendance_csv, db_path)
                    if success:
                        marked_today.add(label_id_str)
                        last_logged_notification = {
                            "name": user_name,
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "expires": current_time + 3.0  # Show for 3 seconds
                        }
                        print(f"[+] Attendance logged: {user_name} (ID: {label_id_str}) at {last_logged_notification['time']}")
                
                # Render user text details (Display name and confidence percentage/distance)
                display_text = f"{user_name} ({match_percentage}%)"
                cv2.putText(frame, display_text, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2, cv2.LINE_AA)
            else:
                user_name = "Unknown"
                box_color = (0, 0, 255)  # Red for unknown
                cv2.putText(frame, "Unknown User", (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2, cv2.LINE_AA)
                
            # Draw box around face
            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
            
        # Draw Notification Banner if active
        if last_logged_notification and current_time < last_logged_notification["expires"]:
            # Renders a sleek pill banner at the top
            banner_y = 50
            banner_h = 35
            banner_w = 400
            banner_x = (w_frame - banner_w) // 2
            
            # Draw banner background (Green translucent pill)
            banner_overlay = frame.copy()
            cv2.rectangle(banner_overlay, (banner_x, banner_y), (banner_x + banner_w, banner_y + banner_h), (0, 100, 0), -1)
            cv2.rectangle(banner_overlay, (banner_x, banner_y), (banner_x + banner_w, banner_y + banner_h), (0, 255, 0), 1)
            
            # Draw text
            notif_text = f"ATTENDANCE MARKED: {last_logged_notification['name']}"
            cv2.putText(banner_overlay, notif_text, (banner_x + 15, banner_y + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            
            # Blend overlay
            cv2.addWeighted(banner_overlay, 0.85, frame, 0.15, 0, frame)
            
        # Display the live feed
        cv2.imshow("Face Recognition Attendance", frame)
        
        # Keystroke capture
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            users = load_users(users_file, db_path)
            marked_today = load_marked_today(attendance_csv, db_path)
            print("[*] User database and today's attendance list reloaded.")
            
    # Clean up
    cap.release()
    cv2.destroyAllWindows()
    print("\nRecognition process finished.")
    input("\nPress Enter to return to terminal...")

if __name__ == "__main__":
    main()
