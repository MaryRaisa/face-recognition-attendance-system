import os
import cv2
import numpy as np
import base64
import shutil
import io
import csv
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, Response, send_file

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

import database

app = Flask(__name__)
app.secret_key = "face_recognition_attendance_secret_key_2026"

# File configurations
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance", "database.db")
ATTENDANCE_CSV = os.path.join(BASE_DIR, "attendance", "attendance.csv")
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
TRAINER_FILE = os.path.join(BASE_DIR, "trainer", "trainer.yml")
CASCADE_PATH = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'

# Ensure base folders exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TRAINER_FILE), exist_ok=True)

# Initialize SQLite database
database.init_db(DB_PATH)

# Helper function to decode base64 images from client-side canvas
def decode_base64_image(image_b64):
    if ',' in image_b64:
        image_b64 = image_b64.split(',')[1]
    image_bytes = base64.b64decode(image_b64)
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return image

# Decorators for route protection
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Admin login required to access this resource.", "error")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'student':
            flash("Student authentication session required.", "error")
            return redirect(url_for('student_login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== WEB PAGES ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html', active_page='home')

@app.route('/student/login')
def student_login():
    if session.get('role') == 'student':
        return redirect(url_for('student_dashboard'))
    return render_template('login.html', active_page='login')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if database.check_admin_login(DB_PATH, username, password):
            session['username'] = username
            session['role'] = 'admin'
            database.add_login_log(DB_PATH, username, 'admin', 'Success')
            flash("Logged in successfully as Admin.", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            database.add_login_log(DB_PATH, username, 'admin', 'Failed')
            flash("Invalid admin username or password.", "error")
            
    return render_template('admin_login.html', active_page='admin_login')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    students = database.get_all_students(DB_PATH)
    
    # Calculate today's attendance count
    today = datetime.now().strftime("%Y-%m-%d")
    all_attendance = database.get_all_attendance(DB_PATH)
    today_attendance_count = sum(1 for att in all_attendance if att['date'] == today)
    
    model_exists = os.path.exists(TRAINER_FILE)
    
    # 1. Daily attendance trend (last 7 days with check-ins)
    conn = database.get_db_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, COUNT(student_id) as count 
        FROM attendance 
        GROUP BY date 
        ORDER BY date DESC 
        LIMIT 7
    """)
    trend_rows = cursor.fetchall()
    conn.close()
    
    # Chronological sort
    trend_rows = list(reversed(trend_rows))
    
    chart_dates = [row['date'] for row in trend_rows]
    chart_counts = [row['count'] for row in trend_rows]
    
    # If no trends, provide placeholders
    if not chart_dates:
        chart_dates = [today]
        chart_counts = [0]
        
    # 2. Compliance Distribution (>= 75% attendance rate)
    compliant_count = 0
    non_compliant_count = 0
    today_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    for s in students:
        s_att = database.get_student_attendance(DB_PATH, s['id'])
        reg_date_str = s['created_at'].split(' ')[0]
        try:
            reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d")
            total_days = (today_date - reg_date).days + 1
        except Exception:
            total_days = 1
            
        rate = (len(s_att) / max(1, total_days)) * 100.0
        if rate >= 75.0:
            compliant_count += 1
        else:
            non_compliant_count += 1
            
    return render_template(
        'admin.html', 
        active_page='admin_dash', 
        students=students, 
        attendance_count=today_attendance_count,
        model_exists=model_exists,
        chart_dates=chart_dates,
        chart_counts=chart_counts,
        compliant_count=compliant_count,
        non_compliant_count=non_compliant_count
    )

@app.route('/admin/register')
@admin_required
def register_student_page():
    return render_template('register.html', active_page='register')

@app.route('/admin/attendance')
@admin_required
def attendance_page():
    logs = database.get_all_attendance(DB_PATH)
    return render_template('attendance.html', active_page='attendance', logs=logs)

@app.route('/admin/history')
@admin_required
def history_page():
    history = database.get_login_history(DB_PATH)
    return render_template('history.html', active_page='history', history=history)

@app.route('/admin/delete_student/<int:student_id>', methods=['POST'])
@admin_required
def delete_student(student_id):
    student = database.get_student_by_id(DB_PATH, student_id)
    if student:
        # Delete dataset folder
        student_dir = os.path.join(DATASET_DIR, student['name'])
        if os.path.exists(student_dir):
            try:
                shutil.rmtree(student_dir)
            except Exception as e:
                print(f"[-] Error deleting student dataset folder: {e}")
                
        database.delete_student(DB_PATH, student_id)
        flash(f"Student '{student['name']}' has been deleted.", "success")
    else:
        flash("Student profile not found.", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/student/dashboard')
@student_required
def student_dashboard():
    student_username = session.get('username')
    student = database.get_student_by_username(DB_PATH, student_username)
    if not student:
        session.clear()
        flash("Session error: Student profile not found in database.", "error")
        return redirect(url_for('student_login'))
        
    attendance_list = database.get_student_attendance(DB_PATH, student['id'])
    login_logs = database.get_student_login_history(DB_PATH, student_username)
    
    # Calculate attendance percentage based on calendar days since registration
    reg_date_str = student['created_at'].split(' ')[0]
    try:
        reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d")
        today_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total_days = (today_date - reg_date).days + 1
    except Exception:
        total_days = 1
        
    attendance_count = len(attendance_list)
    attendance_percentage = (attendance_count / max(1, total_days)) * 100.0
    attendance_percentage = round(min(100.0, attendance_percentage), 1)
    
    is_marked_today = database.is_attendance_marked_today(DB_PATH, student['id'])
    
    return render_template(
        'student.html', 
        active_page='student_dash', 
        student=student, 
        attendance_list=attendance_list,
        login_logs=login_logs,
        attendance_percentage=attendance_percentage,
        is_marked_today=is_marked_today,
        total_days=total_days
    )

@app.route('/admin/export/csv')
@admin_required
def export_attendance_csv():
    logs = database.get_all_attendance(DB_PATH)
    
    # Write to a string buffer
    dest = io.StringIO()
    writer = csv.writer(dest)
    
    # Write header (updated to include Roll Number, Department, and Year)
    writer.writerow(["Date", "Time", "Student ID", "Roll Number", "Student Name", "Username", "Department", "Year", "LBPH Confidence Distance"])
    
    # Write data rows
    for log in logs:
        writer.writerow([
            log['date'],
            log['time'],
            log['student_id'],
            log.get('roll_number') or 'N/A',
            log['name'],
            log['username'],
            log.get('department') or 'N/A',
            log.get('year') or 'N/A',
            f"{log['confidence']:.2f}"
        ])
        
    output = dest.getvalue()
    dest.close()
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_export.csv"}
    )

@app.route('/admin/export/pdf')
@admin_required
def export_attendance_pdf():
    logs = database.get_all_attendance(DB_PATH)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        name='TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#1d4ed8'),
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        name='SubTitleStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#6b7280'),
        spaceAfter=20
    )
    
    cell_style = ParagraphStyle(
        name='CellStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=colors.HexColor('#1f2937')
    )
    
    header_style = ParagraphStyle(
        name='HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=colors.white
    )
    
    elements = []
    
    # Title & Metadata
    elements.append(Paragraph("Face Recognition Attendance System", title_style))
    elements.append(Paragraph(f"Attendance Log Export - Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
    elements.append(Spacer(1, 10))
    
    # Table Data Layout
    # Date, Time, Roll Number, Student Name, Department, Year, Confidence
    data = [[
        Paragraph("Date", header_style),
        Paragraph("Time", header_style),
        Paragraph("Roll Number", header_style),
        Paragraph("Student Name", header_style),
        Paragraph("Department", header_style),
        Paragraph("Year", header_style),
        Paragraph("Score", header_style)
    ]]
    
    for log in logs:
        data.append([
            Paragraph(log['date'], cell_style),
            Paragraph(log['time'], cell_style),
            Paragraph(log.get('roll_number') or 'N/A', cell_style),
            Paragraph(log['name'], cell_style),
            Paragraph(log.get('department') or 'N/A', cell_style),
            Paragraph(log.get('year') or 'N/A', cell_style),
            Paragraph(f"{log['confidence']:.2f}", cell_style)
        ])
        
    # Create Table (Column widths summing to 7.2 inches)
    col_widths = [1.0 * inch, 0.8 * inch, 1.2 * inch, 1.4 * inch, 1.2 * inch, 0.8 * inch, 0.8 * inch]
    t = Table(data, colWidths=col_widths)
    
    # Style Table
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1d4ed8')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f9fafb')]),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('TOPPADDING', (0,1), (-1,-1), 6),
    ]))
    
    elements.append(t)
    doc.build(elements)
    
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='attendance_export.pdf'
    )

# ==================== API ENDPOINTS ====================

@app.route('/api/register_student', methods=['POST'])
@admin_required
def api_register_student():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    username = data.get('username', '').strip()
    roll_number = data.get('roll_number', '').strip()
    department = data.get('department', '').strip()
    year = data.get('year', '').strip()
    
    if not name or not username or not roll_number or not department or not year:
        return jsonify({"status": "error", "message": "All fields (Name, Username, Roll Number, Department, Year) are required."}), 400
        
    student_id = database.add_student(DB_PATH, name, username, roll_number, department, year)
    if student_id:
        # Pre-create directory inside dataset
        student_dir = os.path.join(DATASET_DIR, name)
        os.makedirs(student_dir, exist_ok=True)
        return jsonify({"status": "success", "student_id": student_id})
    else:
        return jsonify({"status": "error", "message": "Username already exists."}), 400

@app.route('/api/register_face', methods=['POST'])
@admin_required
def api_register_face():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    student_name = data.get('student_name', '').strip()
    image_b64 = data.get('image')
    sample_index = data.get('sample_index')
    
    if not student_id or not student_name or not image_b64 or sample_index is None:
        return jsonify({"status": "error", "message": "Missing required data fields."}), 400
        
    try:
        frame = decode_base64_image(image_b64)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(100, 100))
        
        if len(faces) != 1:
            return jsonify({"status": "error", "message": f"Detected {len(faces)} faces. Need exactly 1 face."})
            
        x, y, w, h = faces[0]
        face_crop = gray[y:y+h, x:x+w]
        
        if face_crop.size > 0:
            face_resized = cv2.resize(face_crop, (200, 200), interpolation=cv2.INTER_AREA)
            student_dir = os.path.join(DATASET_DIR, student_name)
            os.makedirs(student_dir, exist_ok=True)
            
            sample_path = os.path.join(student_dir, f"{sample_index}.jpg")
            cv2.imwrite(sample_path, face_resized)
            return jsonify({"status": "success", "message": f"Saved sample {sample_index}"})
        else:
            return jsonify({"status": "error", "message": "Cropped region is empty."})
            
    except Exception as e:
        return jsonify({"status": "error", "message": f"Exception: {str(e)}"}), 500

@app.route('/api/login_face', methods=['POST'])
def api_login_face():
    data = request.get_json() or {}
    image_b64 = data.get('image')
    
    if not image_b64:
        return jsonify({"status": "error", "message": "No image data provided."}), 400
        
    if not os.path.exists(TRAINER_FILE):
        return jsonify({"status": "error", "message": "Trained face recognition model not found."}), 500
        
    try:
        # Load recognizer
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.read(TRAINER_FILE)
        
        frame = decode_base64_image(image_b64)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
        
        if len(faces) == 0:
            return jsonify({"status": "no_face", "message": "No face detected in webcam."})
            
        # Select the largest face if multiple detected (fallback)
        largest_face = max(faces, key=lambda rect: rect[2] * rect[3])
        x, y, w, h = largest_face
        face_crop = gray[y:y+h, x:x+w]
        face_resized = cv2.resize(face_crop, (200, 200), interpolation=cv2.INTER_AREA)
        
        # Predict
        student_id, confidence_dist = recognizer.predict(face_resized)
        
        CONFIDENCE_THRESHOLD = 80.0
        if confidence_dist < CONFIDENCE_THRESHOLD:
            student = database.get_student_by_id(DB_PATH, student_id)
            if student:
                student_name = student['name']
                student_username = student['username']
                
                # Check duplicate attendance on the same day
                is_marked = database.is_attendance_marked_today(DB_PATH, student_id)
                if not is_marked:
                    # Log attendance
                    database.mark_attendance_in_db_and_csv(DB_PATH, student_id, confidence_dist, ATTENDANCE_CSV)
                    database.add_login_log(DB_PATH, student_username, 'student', 'Success')
                    
                    # Store session details
                    session['username'] = student_username
                    session['role'] = 'student'
                    
                    return jsonify({
                        "status": "success", 
                        "name": student_name, 
                        "redirect": url_for('student_dashboard')
                    })
                else:
                    # Already marked but login allowed
                    database.add_login_log(DB_PATH, student_username, 'student', 'Success')
                    session['username'] = student_username
                    session['role'] = 'student'
                    
                    return jsonify({
                        "status": "duplicate", 
                        "name": student_name, 
                        "redirect": url_for('student_dashboard')
                    })
                    
        # If no matched user
        database.add_login_log(DB_PATH, 'Unknown', 'student', 'Failed')
        return jsonify({"status": "unknown", "message": "Unknown face credentials."})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server processing error: {str(e)}"}), 500

@app.route('/api/train_model', methods=['POST'])
@admin_required
def api_train_model():
    students = database.get_all_students(DB_PATH)
    if not students:
        return jsonify({"status": "error", "message": "No registered students in database to train."}), 400
        
    face_samples = []
    ids = []
    
    # Traverse through database records to find directory matches
    for student in students:
        student_id = student['id']
        student_name = student['name']
        student_dir = os.path.join(DATASET_DIR, student_name)
        
        if not os.path.exists(student_dir):
            continue
            
        # Fetch JPEG/JPG samples
        image_paths = [os.path.join(student_dir, f) for f in os.listdir(student_dir) if f.endswith((".jpg", ".jpeg"))]
        for path in image_paths:
            try:
                gray_img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if gray_img is None:
                    continue
                face_samples.append(gray_img)
                ids.append(student_id)
            except Exception as e:
                print(f"[-] Failed to load image {path}: {e}")
                
    if not face_samples:
        return jsonify({"status": "error", "message": "No valid face samples (.jpg) found inside dataset folders."}), 400
        
    try:
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.train(face_samples, np.array(ids))
        recognizer.write(TRAINER_FILE)
        
        return jsonify({
            "status": "success",
            "message": f"Model trained on {len(face_samples)} frames for {len(set(ids))} registered students."
        })
    except AttributeError:
        return jsonify({"status": "error", "message": "OpenCV contrib module (cv2.face) is not available on this server."}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Initialize port 5000 and enable debug mode for local deployment verification
    app.run(host='0.0.0.0', port=5000, debug=True)
