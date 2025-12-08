from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import hashlib
from datetime import datetime
import pyrebase
import re
import logging

# basic logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ===== Firebase Configuration =====
config = {
    "apiKey": "AIzaSyAzCdKIW2uEwMzsMFkK5Pu8MbcjPGAwF-w",
    "authDomain": "teacherstatustracker.firebaseapp.com",
    "databaseURL": "https://teacherstatustracker-default-rtdb.firebaseio.com",
    "storageBucket": "teacherstatustracker.appspot.com"
}

firebase = pyrebase.initialize_app(config)
db = firebase.database()

# ===== Helper Functions =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def validate_password(password):
    pattern = r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).+$'
    return bool(re.match(pattern, password))

def get_current_lecture(schedule):
    now = datetime.now()
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M")
    in_lecture = None
    if current_day in schedule:
        day_schedule = schedule[current_day]
        if isinstance(day_schedule, list):
            day_schedule = {str(i): room for i, room in enumerate(day_schedule)}
        for time_slot, room in day_schedule.items():
            try:
                start, end = time_slot.split("-")
                if start <= current_time <= end:
                    in_lecture = f"IN LECTURE at {room}"
                    break
            except Exception:
                continue
    return in_lecture

def calculate_status(teacher):
    now = datetime.now()
    current_day = now.strftime("%A")
    schedule = teacher.get("schedule", {}) or {}
    status = teacher.get("status", "Available")
    calculated_status = "Available"
    try:
        if current_day in schedule and isinstance(schedule[current_day], dict):
            for time_slot, room_subject in schedule[current_day].items():
                try:
                    start, end = time_slot.split("-")
                    if start <= now.strftime("%H:%M") <= end:
                        calculated_status = f"Busy in {room_subject}"
                        break
                except Exception:
                    continue
    except Exception:
        pass

    if "ON LEAVE" in str(status).upper():
        calculated_status = "On Leave"
    return calculated_status, current_day, now.strftime("%H:%M")

# Utility: recursively find report dicts and count issues
def flatten_reports(reports_obj):
    """
    Convert various possible Firebase shapes into a flat dictionary:
      { "timestamp_str": {Monitors:.., CPU:.., ...}, ... }

    Handles:
      - flat mapping timestamp -> report (common)
      - nested mapping like month->{day->{timestamp->report}}
      - other nested combinations
    """
    flat = {}

    def _walk(key_prefix, obj):
        if isinstance(obj, dict):
            # Heuristic: if dict values are ints or dict of equipment -> int?
            # If obj looks like a report (contains equipment keys), treat it as report.
            # We'll consider it a report if ANY of the expected keys appear.
            expected_keys = {"Monitors", "CPU", "Mouse", "Keyboard", "Switches"}
            if expected_keys & set(obj.keys()):
                # treat current object as the report; use key_prefix as timestamp if available
                timestamp_key = key_prefix or "unknown"
                flat[timestamp_key] = obj
                return
            # Otherwise, descend
            for k, v in obj.items():
                # Build nested key (prefer last-level timestamp if present)
                next_prefix = k if not key_prefix else f"{key_prefix} {k}"
                _walk(next_prefix, v)
        else:
            # not a dict (int, None...), ignore
            return

    _walk("", reports_obj)
    return flat

def count_reports_and_issues(reports_obj):
    flat = flatten_reports(reports_obj)
    total_reports = 0
    total_issues = 0
    for ts, rep in flat.items():
        if isinstance(rep, dict):
            total_reports += 1
            # sum only integer values
            total_issues += sum(v for v in rep.values() if isinstance(v, int))
    return total_reports, total_issues, flat

# ===== Setup Defaults =====
def setup_defaults():
    try:
        if not db.child("admins").child("admin1").get().val():
            db.child("admins").child("admin1").set({
                "name": "Super Admin",
                "password": hash_password("admin123")
            })
            logging.info("✅ Default admin created!")
        else:
            logging.info("ℹ️ Admin already exists, skipping setup.")
    except Exception as e:
        logging.exception("Error during setup_defaults: %s", e)

# ===== Login =====
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "")

        if not user_id or not password:
            flash("❌ User ID and Password are required!", "danger")
            return redirect(request.url)

        try:
            # Admin check
            admin = db.child("admins").child(user_id).get().val()
            if admin and admin.get("password") == hash_password(password):
                session["role"] = "admin"
                session["user_id"] = user_id
                return redirect(url_for("admin_dashboard"))

            # Teacher check
            teacher = db.child("teachers").child(user_id).get().val()
            if teacher and teacher.get("password") == hash_password(password):
                session["role"] = "teacher"
                session["user_id"] = user_id
                return redirect(url_for("teacher_dashboard"))

            # Lab check
            lab = db.child("labs").child(user_id).get().val()
            if lab and lab.get("password") == hash_password(password):
                session["role"] = "lab"
                session["user_id"] = user_id
                return redirect(url_for("lab_dashboard"))

            # Student check
            student = db.child("students").child(user_id).get().val()
            if student and student.get("password") == hash_password(password):
                session["role"] = "student"
                session["user_id"] = user_id
                return redirect(url_for("student_dashboard"))
        except Exception as e:
            logging.exception("Error checking credentials: %s", e)
            flash("❌ Error authenticating, try again.", "danger")
            return redirect(request.url)

        flash("❌ Invalid credentials!", "danger")
    return render_template("login.html")

# ===== Admin Dashboard =====
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect("/")
    teachers = db.child("teachers").get().val() or {}
    labs = db.child("labs").get().val() or {}
    students = db.child("students").get().val() or {}
    return render_template("admin_dashboard.html", teachers=teachers, labs=labs, students=students)

# ===== Admin Teacher Manage =====
@app.route("/admin_teacher_manage", methods=["GET", "POST"])
def admin_teacher_manage():
    if session.get("role") != "admin":
        return redirect("/")
    teachers = db.child("teachers").get().val() or {}
    return render_template("admin_teacher_manage.html", teachers=teachers)

@app.route("/admin/add_teacher", methods=["POST"])
def add_teacher():
    if session.get("role") != "admin":
        return redirect("/")
    code = request.form.get("short_code", "").upper()
    name = request.form.get("name", "")
    password = request.form.get("password", "")

    if not code or not name or not password:
        flash("❌ All fields are required!", "danger")
        return redirect(url_for("admin_teacher_manage"))

    if not validate_password(password):
        flash("❌ Weak password! Must include letters, numbers, and symbols.", "danger")
        return redirect(url_for("admin_teacher_manage"))

    db.child("teachers").child(code).set({
        "name": name,
        "password": hash_password(password),
        "status": "No status yet",
        "last_updated": "Never",
        "schedule": {}
    })
    flash(f"✅ Teacher {name} added!", "success")
    return redirect(url_for("admin_teacher_manage"))

@app.route("/admin/remove_teacher/<code>")
def remove_teacher(code):
    if session.get("role") != "admin":
        return redirect("/")
    db.child("teachers").child(code).remove()
    flash(f"❌ Teacher {code} removed!", "warning")
    return redirect(url_for("admin_teacher_manage"))

# ===== Admin Lab Manage =====
@app.route("/admin_lab_manage", methods=["GET", "POST"])
def admin_lab_manage():
    if session.get("role") != "admin":
        return redirect("/")

    labs_dict = db.child("labs").get().val() or {}
    labs = []

    for lab_id, lab_data in labs_dict.items():
        reports_obj = lab_data.get("reports", {}) or {}
        total_reports, total_issues, _flat = count_reports_and_issues(reports_obj)
        # if systems not set, default to 0
        systems = lab_data.get("systems", 0) if isinstance(lab_data.get("systems", 0), int) else 0
        issues = lab_data.get("issues", 0) if isinstance(lab_data.get("issues", 0), int) else total_issues

        labs.append({
            "id": lab_id,
            "name": lab_data.get("name", ""),
            "password": lab_data.get("password", ""),
            # Use integer counts for template
            "reports": total_reports,
            "systems": systems,
            "issues": issues
        })

    return render_template("admin_lab_manage.html", labs=labs)

# ===== Add Lab =====
@app.route("/admin/add_lab", methods=["POST"])
def add_lab():
    if session.get("role") != "admin":
        return redirect("/")

    lab_id = request.form.get("lab_id", "").strip()
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()

    if not lab_id or not name or not password:
        flash("❌ All fields are required!", "danger")
        return redirect(url_for("admin_lab_manage"))

    if not validate_password(password):
        flash("❌ Weak password! Must include letters, numbers, and symbols.", "danger")
        return redirect(url_for("admin_lab_manage"))

    db.child("labs").child(lab_id).set({
        "name": name,
        "password": hash_password(password),
        "reports": {},
        "systems": 0,
        "issues": 0
    })

    flash(f"✅ Lab {name} added!", "success")
    return redirect(url_for("admin_lab_manage"))

# ===== Remove Lab =====
@app.route("/admin/remove_lab/<lab_id>")
def remove_lab(lab_id):
    if session.get("role") != "admin":
        return redirect("/")
    db.child("labs").child(lab_id).remove()
    flash(f"❌ Lab {lab_id} removed!", "warning")
    return redirect(url_for("admin_lab_manage"))

# ===== Get Lab Details (JSON for modal) =====
@app.route("/lab/<lab_id>")
def get_lab(lab_id):
    """Return lab details in JSON for modal view."""
    if session.get("role") != "admin":
        return jsonify({"error": "not authorized"}), 403

    lab_data = db.child("labs").child(lab_id).get().val()
    if not lab_data:
        return jsonify({"error": "Lab not found"}), 404

    reports_obj = lab_data.get("reports", {}) or {}
    total_reports, total_issues, flat = count_reports_and_issues(reports_obj)

    return jsonify({
        "lab_id": lab_id,
        "lab_name": lab_data.get("name", ""),
        # include raw flattened reports for UI
        "reports": flat,
        "reports_count": total_reports,
        "systems": lab_data.get("systems", 0),
        "issues": total_issues
    })



# ===== Admin View Lab Reports =====
@app.route("/admin/lab/<lab_id>/reports")
def lab_reports(lab_id):
    if session.get("role") != "admin":
        return redirect("/")

    lab_data = db.child("labs").child(lab_id).get().val()
    if not lab_data:
        flash("❌ Lab not found!", "danger")
        return redirect(url_for("admin_lab_manage"))

    lab = {
        "id": lab_id,
        "name": lab_data.get("name", "Unknown"),
        "systems": lab_data.get("systems", 0),
        "issues": lab_data.get("issues", 0),
    }

    reports_obj = lab_data.get("reports", {})
    grouped_reports = sanitize_and_group_reports(reports_obj)

    return render_template("lab_reports.html", lab=lab, reports=grouped_reports)








# ===== Admin Teacher Status =====
@app.route("/admin_teacher_status")
def admin_teacher_status():
    if session.get("role") != "admin":
        return redirect("/")

    teachers = db.child("teachers").get().val() or {}
    updated_teachers = {}
    for code, teacher in teachers.items():
        calculated_status, current_day, current_time = calculate_status(teacher)
        updated_teachers[code] = {
            "name": teacher.get("name", "Unknown"),
            "status": calculated_status,
            "last_updated": teacher.get("last_updated", "Never"),
            "schedule": teacher.get("schedule", {})
        }

    return render_template(
        "admin_teacher_status.html",
        teachers=updated_teachers,
        current_day=datetime.now().strftime("%A"),
        current_time=datetime.now().strftime("%H:%M")
    )


def get_current_lecture(schedule):
    """
    Returns the current lecture info as dict:
      {"room": ..., "subject": ..., "time_slot": ...}
    """
    now = datetime.now()
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M")  # logic uses 24-hour

    if current_day not in schedule:
        return None

    day_schedule = schedule[current_day]
    if isinstance(day_schedule, list):
        day_schedule = {str(i): room for i, room in enumerate(day_schedule)}

    for time_slot, entry in day_schedule.items():
        try:
            start, end = time_slot.split("-")
            if start <= current_time <= end:
                # entry can be dict {"room":..., "subject":...} or string "Room / Subject"
                if isinstance(entry, dict):
                    room = entry.get("room", "")
                    subject = entry.get("subject", "")
                else:
                    parts = entry.split(" / ")
                    room = parts[0] if len(parts) > 0 else ""
                    subject = parts[1] if len(parts) > 1 else ""
                return {"room": room, "subject": subject, "time_slot": time_slot}
        except Exception:
            continue

    return None


# ===== Teacher Dashboard =====
@app.route("/teacher", methods=["GET", "POST"])
def teacher_dashboard():
    if session.get("role") != "teacher":
        return redirect("/")

    code = session["user_id"]
    teacher = db.child("teachers").child(code).get().val() or {}
    schedule = teacher.get("schedule", {})

    # Update status
    if request.method == "POST":
        status = request.form.get("status_type", "")
        room = request.form.get("room", "")
        leave_date = request.form.get("leave_date", "")
        if status == "AVAILABLE":
            status_text = f"AVAILABLE in Room {room}" if room else "AVAILABLE"
        elif status == "NOT AVAILABLE":
            status_text = "NOT AVAILABLE"
        elif status == "ON LEAVE":
            status_text = f"ON LEAVE until {leave_date}" if leave_date else "ON LEAVE"
        else:
            status_text = teacher.get("status", "No status")

        db.child("teachers").child(code).update({
            "status": status_text,
            "last_updated": datetime.now().strftime("%d/%m/%Y %I:%M %p")  # 12-hour format
        })
        flash("✅ Status updated!", "success")

    # Fetch updated info
    teacher = db.child("teachers").child(code).get().val() or {}
    current_lecture = get_current_lecture(schedule)
    display_status = f"IN LECTURE at {current_lecture['room']} / {current_lecture['subject']}" if current_lecture else teacher.get("status", "No status")

    # Today's schedule
    today_schedule = schedule.get(datetime.now().strftime("%A"), {})
    # Convert any string entries to dict if needed
    for k, v in list(today_schedule.items()):
        if isinstance(v, str):
            parts = v.split(" / ")
            today_schedule[k] = {"room": parts[0], "subject": parts[1] if len(parts) > 1 else ""}

    return render_template(
        "teacher_dashboard.html",
        teacher=teacher,
        display_status=display_status,
        schedule=today_schedule,
        current_day=datetime.now().strftime("%A"),
        current_time=datetime.now().strftime("%I:%M %p")  # 12-hour for display
    )

# ===== Teacher Schedule =====
@app.route("/teacher/schedule", methods=["GET", "POST"])
def teacher_schedule():
    if session.get("role") != "teacher":
        return redirect("/")

    code = session["user_id"]
    teacher = db.child("teachers").child(code).get().val() or {}
    schedule = teacher.get("schedule", {})

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":  # Add/Update subject
            day = request.form.get("day")
            time_slot = request.form.get("time_slot")
            room = request.form.get("room")
            subject = request.form.get("subject")

            if day and time_slot and room and subject:
                db.child("teachers").child(code).child("schedule").child(day).child(time_slot).set({
                    "room": room,
                    "subject": subject
                })
                flash(f"✅ Schedule updated: {day} {time_slot} → {room} / {subject}", "success")
            else:
                flash("❌ All fields are required!", "danger")

        elif action == "delete":  # Remove subject
            day = request.form.get("day")
            time_slot = request.form.get("time_slot")

            if day and time_slot:
                db.child("teachers").child(code).child("schedule").child(day).child(time_slot).remove()
                flash(f"🗑 Deleted schedule: {day} {time_slot}", "info")
            else:
                flash("❌ Day & Time Slot required to delete!", "danger")

        return redirect(url_for("teacher_schedule"))

    return render_template("teacher_schedule.html", teacher=teacher, schedule=schedule)



def sanitize_report(report):
    """Ensure report dict has all required keys with integer values."""
    keys = ["Monitors", "CPU", "Mouse", "Keyboard", "Switches"]
    if not isinstance(report, dict):
        report = {key: 0 for key in keys}
    else:
        for key in keys:
            if key not in report or not isinstance(report[key], int):
                report[key] = 0
    return report

def sanitize_and_group_reports(reports_obj):
    """Convert flat or nested reports into month->day->timestamp->report structure."""
    grouped_reports = {}
    if not isinstance(reports_obj, dict):
        return grouped_reports

    for tstamp, report in sorted(reports_obj.items(), reverse=True):
        report = sanitize_report(report)
        try:
            dt = datetime.strptime(tstamp, "%Y-%m-%d %H:%M:%S")
            month = dt.strftime("%B %Y")
            day = dt.strftime("%d-%m-%Y")
        except Exception:
            month = "Unknown"
            day = "Unknown"

        grouped_reports.setdefault(month, {}).setdefault(day, {})[tstamp] = report

    return grouped_reports
# ===== Lab Dashboard =====
@app.route("/lab", methods=["GET", "POST"])
def lab_dashboard():
    if session.get("role") != "lab":
        return redirect("/")

    lab_id = session["user_id"]
    lab_data = db.child("labs").child(lab_id).get().val() or {}

    # Handle new report submission
    if request.method == "POST":
        report = {}
        for key in ["Monitors", "CPU", "Mouse", "Keyboard", "Switches"]:
            try:
                report[key] = int(request.form.get(key, 0))
            except Exception:
                report[key] = 0

        # Optional: add other issues
        other_issues = request.form.get("OtherIssues", "").strip()
        if other_issues:
            report["OtherIssues"] = other_issues

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.child("labs").child(lab_id).child("reports").child(timestamp).set(report)
        flash("✅ Report saved!", "success")

        # Reload lab data to include new report
        lab_data = db.child("labs").child(lab_id).get().val() or {}

    # Get reports safely
    reports_obj = lab_data.get("reports", {})

    # 🔥 Ensure it's always a dict (avoid 'int object has no attribute items')
    if not isinstance(reports_obj, dict):
        reports_obj = {}

    # Group reports (your helper function)
    grouped_reports = sanitize_and_group_reports(reports_obj)

    # Lab info
    lab = {
        "id": lab_id,
        "name": lab_data.get("name", "Unknown"),
        "systems": lab_data.get("systems", 0),
        "issues": lab_data.get("issues", 0),
    }

    return render_template("lab_dashboard.html", lab_id=lab_id, lab=lab, reports=grouped_reports)


# ===== Remove Lab Report =====
@app.route("/remove_lab_report", methods=["POST"])
def remove_lab_report():
    if session.get("role") != "lab":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    lab_id = session["user_id"]
    timestamp = request.form.get("timestamp")

    if not timestamp:
        return jsonify({"success": False, "error": "No timestamp provided"}), 400

    try:
        # Remove the report from Firebase
        db.child("labs").child(lab_id).child("reports").child(timestamp).remove()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ===== Student Dashboard =====
@app.route("/student")
def student_dashboard():
    if session.get("role") != "student":
        return redirect("/")

    teachers = db.child("teachers").get().val() or {}
    current_day = datetime.now().strftime("%A")
    current_time = datetime.now().strftime("%H:%M")  # 24-hour for comparison

    for code, teacher in teachers.items():
        teacher_schedule = teacher.get("schedule", {})
        today_schedule = teacher_schedule.get(current_day, {})

        # 🔥 Normalize if it's a list
        if isinstance(today_schedule, list):
            today_schedule = {str(i): v for i, v in enumerate(today_schedule)}

        teacher["current_lecture"] = None
        if today_schedule:
            for time_slot, lecture in today_schedule.items():
                if isinstance(lecture, dict) and " - " in time_slot:
                    start, end = [t.strip() for t in time_slot.split("-")]
                    if start <= current_time <= end:
                        teacher["current_lecture"] = {
                            "room": lecture.get("room", "Unknown"),
                            "subject": lecture.get("subject", "")
                        }
                        break

    return render_template(
        "student_dashboard.html",
        teachers=teachers,
        current_day=current_day,
        current_time=datetime.now().strftime("%I:%M %p")  # 12h for display
    )












# ===== Logout =====
@app.route("/logout")
def logout():
    session.clear()
    flash("✅ Logged out successfully!", "success")
    return redirect("/")

# ===== Password Reset =====
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        code = request.form.get("short_code", "").upper()
        new_password = request.form.get("new_password", "")

        teacher = db.child("teachers").child(code).get().val()
        if not teacher:
            flash("❌ Invalid short code!", "danger")
            return redirect(url_for("forgot_password"))

        if not validate_password(new_password):
            flash("❌ Password must contain letters, numbers, and symbols.", "danger")
            return redirect(url_for("forgot_password"))

        db.child("teachers").child(code).update({"password": hash_password(new_password)})
        flash("✅ Password reset successfully!", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")

if __name__ == "__main__":
    setup_defaults()
    app.run(debug=True)
