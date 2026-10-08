from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import json
import os
import razorpay
from dotenv import load_dotenv
from flask_mail import Mail, Message
import secrets

# Load environment variables from .env
load_dotenv()

app = Flask(__name__,
            template_folder="app/templates",
            static_folder="app/static")

# Flask session secret
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-me')

# Razorpay configuration
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET')

# Razorpay client (initialize once)
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# File upload config
UPLOAD_FOLDER = 'app/static/uploads/products'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__,
            template_folder="app/templates",
            static_folder="app/static")
app.secret_key = 'your-secret-key-change-me'

UPLOAD_FOLDER = 'app/static/uploads/products'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==================== EMAIL CONFIGURATION ====================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@partmatch.com')

mail = Mail(app)

def send_email(to, subject, body_html):
    """Send email safely — won't crash app if mail fails"""
    if not app.config['MAIL_USERNAME']:
        print(f"[MAIL SKIP] Would send to {to}: {subject}")
        return False
    try:
        msg = Message(subject=subject, recipients=[to], html=body_html)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False
    
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_compatibility(compat_json, user_vehicles):
    """
    Returns True if the product compatibility matches any of the user's vehicles.
    If the product has no compatibility info (universal), returns False.
    """
    if not compat_json or not user_vehicles:
        return False
    try:
        compat = json.loads(compat_json) if isinstance(compat_json, str) else compat_json
    except:
        return False
    
    if not isinstance(compat, dict):
        return False
    
    prod_make = (compat.get('make') or '').strip().lower()
    prod_model = (compat.get('model') or '').strip().lower()
    
    if not prod_make and not prod_model:
        return False
    
    for v in user_vehicles:
        v_make = (v.get('make') or '').strip().lower()
        v_model = (v.get('model') or '').strip().lower()
        
        make_match = (not prod_make) or (prod_make in v_make or v_make in prod_make)
        model_match = (not prod_model) or (prod_model in v_model or v_model in prod_model)
        
        if make_match and model_match:
            return True
    return False
# ------------------ MySQL connection helper ------------------
def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',          # change to your MySQL user
        password='',  # change to your MySQL password
        database='partmatch_db',
        cursorclass=pymysql.cursors.DictCursor
    )

# ------------------ Homepage ------------------
# ------------------ Homepage ------------------
@app.route('/')
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Featured products
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.image, p.brand,
               pc.name as category_name,
               u.name as vendor_name,
               vd.business_name,
               (SELECT AVG(rating) FROM reviews WHERE product_id = p.id) as avg_rating,
               (SELECT COUNT(*) FROM reviews WHERE product_id = p.id) as review_count
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        JOIN users u ON p.vendor_id = u.id
        LEFT JOIN vendor_details vd ON u.id = vd.user_id
        WHERE p.is_approved = 1 AND p.stock_quantity > 0
        ORDER BY avg_rating DESC, p.created_at DESC
        LIMIT 6
    """)
    featured_products = cursor.fetchall()
    
    # Platform stats
    cursor.execute("SELECT COUNT(*) as total FROM products WHERE is_approved = 1")
    total_products = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM vendor_details WHERE is_approved = 1")
    total_vendors = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM service_center_details WHERE is_approved = 1")
    total_centers = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    return render_template('base.html',
                         featured_products=featured_products,
                         total_products=total_products,
                         total_vendors=total_vendors,
                         total_centers=total_centers)

# ------------------ Registration (from modal) ------------------
@app.route('/register', methods=['POST'])
def register():
    # Get common fields
    email = request.form.get('regEmail')
    password = request.form.get('regPass')
    name = request.form.get('regName')
    phone = request.form.get('regPhone')
    role = request.form.get('regRole')      # hidden input set by JS: 'customer','vendor','service_center'

    if not email or not password or not name or not phone or not role:
        flash('Please fill all required fields.', 'danger')
        return redirect(url_for('home'))

    # Hash password
    hashed_pw = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check if email exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('Email already registered.', 'danger')
            return redirect(url_for('home'))

        # Insert into users
        cursor.execute(
            "INSERT INTO users (email, password_hash, role, name, phone, is_verified) VALUES (%s,%s,%s,%s,%s,%s)",
            (email, hashed_pw, role, name, phone, False)
        )
        user_id = cursor.lastrowid

        # Role-specific inserts
        if role == 'vendor':
            business_name = request.form.get('regBusinessName')
            gst = request.form.get('regGst')
            address = request.form.get('regBusinessAddress')
            city = request.form.get('regCity')
            pincode = request.form.get('regPincode')
            category = request.form.get('regCategory')
            cursor.execute(
                "INSERT INTO vendor_details (user_id, business_name, gst_number, address, city, pincode) VALUES (%s,%s,%s,%s,%s,%s)",
                (user_id, business_name, gst, address, city, pincode)
            )
        elif role == 'service_center':
            center_name = request.form.get('regCenterName')
            address = request.form.get('regCenterAddress')
            city = request.form.get('regCenterCity')
            pincode = request.form.get('regCenterPincode')
            reg_number = request.form.get('regCenterReg')
            bays = request.form.get('regBays')
            specialization = request.form.get('regSpecialization')
            open_time = request.form.get('regOpenTime')
            close_time = request.form.get('regCloseTime')
            # Assuming you created a table service_center_details (see below)
            cursor.execute(
                "INSERT INTO service_center_details (user_id, center_name, address, city, pincode, registration_number, service_bays, specialization, open_time, close_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (user_id, center_name, address, city, pincode, reg_number, bays, specialization, open_time, close_time)
            )

        conn.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('home'))
    except Exception as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('home'))
    finally:
        cursor.close()
        conn.close()

# ------------------ Login ------------------
@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('loginEmail')
    password = request.form.get('loginPass')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and check_password_hash(user['password_hash'], password):
        role = user['role']

        # ---- CUSTOMER ----
        if role == 'customer':
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['name']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(url_for('customer_dashboard'))

        # ---- VENDOR ----
        elif role == 'vendor':
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT is_approved FROM vendor_details WHERE user_id = %s", (user['id'],))
            vendor = cursor.fetchone()
            cursor.close()
            conn.close()

            if vendor and vendor['is_approved']:
                session['user_id'] = user['id']
                session['role'] = user['role']
                session['user_name'] = user['name']
                flash(f'Welcome back, {user["name"]}!', 'success')
                return redirect(url_for('vendor_dashboard'))
            else:
                flash('Your vendor account is pending admin approval.', 'warning')
                return redirect(url_for('home'))

        # ---- SERVICE CENTER ----
        elif role == 'service_center':
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT is_approved FROM service_center_details WHERE user_id = %s", (user['id'],))
            center = cursor.fetchone()
            cursor.close()
            conn.close()

            if center and center['is_approved']:
                session['user_id'] = user['id']
                session['role'] = user['role']
                session['user_name'] = user['name']
                flash(f'Welcome back, {user["name"]}!', 'success')
                return redirect(url_for('service_center_dashboard'))
            else:
                flash('Your service center account is pending admin approval.', 'warning')
                return redirect(url_for('home'))

        # ---- ADMIN ----
        elif role == 'admin':
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['name']
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))

    else:
        flash('Invalid email or password.', 'danger')
        return redirect(url_for('home'))
    
    
# ------------------ Logout ------------------
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

# ------------------ Customer Dashboard ------------------
# ------------------ Customer Dashboard ------------------
@app.route('/customer/dashboard')
def customer_dashboard():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Count vehicles
    cursor.execute("SELECT COUNT(*) as total FROM vehicles WHERE user_id = %s", (customer_id,))
    vehicle_count = cursor.fetchone()['total']
    
    # Get user's vehicles
    cursor.execute("SELECT * FROM vehicles WHERE user_id = %s ORDER BY created_at DESC LIMIT 3", (customer_id,))
    vehicles = cursor.fetchall()
    
    # Recent orders
    cursor.execute("""
        SELECT o.*, COUNT(oi.id) as item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        WHERE o.customer_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 5
    """, (customer_id,))
    recent_orders = cursor.fetchall()
    
    # Total orders
    cursor.execute("SELECT COUNT(*) as total FROM orders WHERE customer_id = %s", (customer_id,))
    order_count = cursor.fetchone()['total']
    
    # Available approved products
    cursor.execute("SELECT COUNT(*) as total FROM products WHERE is_approved = 1 AND stock_quantity > 0")
    available_products = cursor.fetchone()['total']
    
    # Upcoming bookings
    cursor.execute("""
        SELECT sb.*, sc.center_name as station_name 
        FROM service_bookings sb
        JOIN service_center_details sc ON sb.station_id = sc.user_id
        WHERE sb.customer_id = %s AND sb.booking_date >= CURDATE()
        ORDER BY sb.booking_date ASC
        LIMIT 3
    """, (customer_id,))
    upcoming_bookings = cursor.fetchall()
    
    # ==================== MAINTENANCE ALERTS ====================
    # Generate alerts based on vehicle maintenance records and last service dates
    maintenance_alerts = []
    today = datetime.now().date()
    
    # Rule-based alert generation: check each vehicle's latest maintenance records
    cursor.execute("""
        SELECT v.id, v.make, v.model, v.registration_number, v.year,
               mr.service_type, mr.next_due_date, mr.next_due_mileage_km, 
               mr.mileage_km, mr.created_at
        FROM vehicles v
        LEFT JOIN maintenance_records mr ON v.id = mr.vehicle_id
        WHERE v.user_id = %s
        ORDER BY v.id, mr.created_at DESC
    """, (customer_id,))
    all_records = cursor.fetchall()
    
    # Group by vehicle
    vehicle_records = {}
    for r in all_records:
        vid = r['id']
        if vid not in vehicle_records:
            vehicle_records[vid] = {
                'vehicle': r,
                'records': []
            }
        if r['service_type']:
            vehicle_records[vid]['records'].append(r)
    
    # Generate alerts per vehicle
    for vid, data in vehicle_records.items():
        v = data['vehicle']
        vehicle_label = f"{v['make']} {v['model']}"
        if v.get('registration_number'):
            vehicle_label += f" ({v['registration_number']})"
        
        if not data['records']:
            # No service history at all — recommend first service
            maintenance_alerts.append({
                'level': 'info',
                'icon': '🆕',
                'title': 'New Vehicle',
                'message': f"{vehicle_label} has no service history. Consider booking a general inspection.",
                'vehicle': vehicle_label,
                'vehicle_id': vid
            })
            continue
        
        # Check latest record for each service type
        seen_types = set()
        for rec in data['records']:
            stype = rec['service_type']
            if stype in seen_types:
                continue
            seen_types.add(stype)
            
            # Check next_due_date
            if rec['next_due_date']:
                due = rec['next_due_date']
                days_until = (due - today).days
                
                if days_until < 0:
                    maintenance_alerts.append({
                        'level': 'danger',
                        'icon': '⚠️',
                        'title': f'{stype} overdue',
                        'message': f"{vehicle_label} — {stype} was due {abs(days_until)} day(s) ago on {due.strftime('%d %b %Y')}.",
                        'vehicle': vehicle_label,
                        'vehicle_id': vid,
                        'due_date': due
                    })
                elif days_until <= 15:
                    maintenance_alerts.append({
                        'level': 'warning',
                        'icon': '🔔',
                        'title': f'{stype} due soon',
                        'message': f"{vehicle_label} — {stype} is due in {days_until} day(s) on {due.strftime('%d %b %Y')}.",
                        'vehicle': vehicle_label,
                        'vehicle_id': vid,
                        'due_date': due
                    })
                elif days_until <= 30:
                    maintenance_alerts.append({
                        'level': 'info',
                        'icon': '📅',
                        'title': f'{stype} upcoming',
                        'message': f"{vehicle_label} — {stype} due in {days_until} days.",
                        'vehicle': vehicle_label,
                        'vehicle_id': vid,
                        'due_date': due
                    })
    
    # Smart recommendation based on mileage (if next_due_mileage available)
    cursor.execute("""
        SELECT DISTINCT v.id, v.make, v.model, v.registration_number,
               MAX(mr.mileage_km) as last_mileage,
               MAX(mr.next_due_mileage_km) as next_due_mileage,
               MAX(mr.service_type) as last_service
        FROM vehicles v
        JOIN maintenance_records mr ON v.id = mr.vehicle_id
        WHERE v.user_id = %s
        GROUP BY v.id, v.make, v.model, v.registration_number
    """, (customer_id,))
    mileage_info = cursor.fetchall()
    
    for m in mileage_info:
        if m['next_due_mileage'] and m['last_mileage']:
            remaining = m['next_due_mileage'] - m['last_mileage']
            if remaining <= 1000:
                vehicle_label = f"{m['make']} {m['model']}"
                if m['registration_number']:
                    vehicle_label += f" ({m['registration_number']})"
                maintenance_alerts.append({
                    'level': 'warning' if remaining > 0 else 'danger',
                    'icon': '🛣️',
                    'title': f"{m['last_service'] or 'Service'} by mileage",
                    'message': f"{vehicle_label} — Next service due in {max(remaining, 0)} km (at {m['next_due_mileage']} km).",
                    'vehicle': vehicle_label,
                    'vehicle_id': m['id']
                })
    
    # Sort alerts by severity
    severity_order = {'danger': 0, 'warning': 1, 'info': 2}
    maintenance_alerts.sort(key=lambda x: severity_order.get(x['level'], 3))
    
    # ==================== END MAINTENANCE ALERTS ====================
    
    cursor.close()
    conn.close()
    
    return render_template('customer/dashboard.html',
                         vehicle_count=vehicle_count,
                         vehicles=vehicles,
                         recent_orders=recent_orders,
                         order_count=order_count,
                         available_products=available_products,
                         upcoming_bookings=upcoming_bookings,
                         maintenance_alerts=maintenance_alerts)
# ------------------ Vendor Dashboard ------------------
@app.route('/vendor/dashboard')
def vendor_dashboard():
    if 'user_id' not in session or session.get('role') != 'vendor':
        flash('Please login as a vendor.', 'warning')
        return redirect(url_for('home'))
    
    vendor_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Product stats
    cursor.execute("SELECT COUNT(*) as total FROM products WHERE vendor_id = %s", (vendor_id,))
    total_products = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM products WHERE vendor_id = %s AND is_approved = 1", (vendor_id,))
    approved_products = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM products WHERE vendor_id = %s AND is_approved = 0", (vendor_id,))
    pending_products = cursor.fetchone()['total']
    
    # Orders for this vendor's products
    cursor.execute("""
        SELECT COUNT(DISTINCT o.id) as total 
        FROM orders o 
        JOIN order_items oi ON o.id = oi.order_id 
        JOIN products p ON oi.product_id = p.id 
        WHERE p.vendor_id = %s
    """, (vendor_id,))
    total_orders = cursor.fetchone()['total']
    
    # Recent products
    cursor.execute("""
        SELECT p.*, pc.name as category_name 
        FROM products p 
        LEFT JOIN product_categories pc ON p.category_id = pc.id 
        WHERE p.vendor_id = %s 
        ORDER BY p.created_at DESC 
        LIMIT 10
    """, (vendor_id,))
    products = cursor.fetchall()
    
    # Recent orders
    cursor.execute("""
        SELECT DISTINCT o.*, u.name as customer_name 
        FROM orders o 
        JOIN order_items oi ON o.id = oi.order_id 
        JOIN products p ON oi.product_id = p.id 
        JOIN users u ON o.customer_id = u.id 
        WHERE p.vendor_id = %s 
        ORDER BY o.created_at DESC 
        LIMIT 10
    """, (vendor_id,))
    recent_orders = cursor.fetchall()
        # Recent reviews for this vendor's products
    cursor.execute("""
        SELECT r.*, u.name as customer_name, p.name as product_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        JOIN products p ON r.product_id = p.id
        WHERE p.vendor_id = %s
        ORDER BY r.created_at DESC
        LIMIT 5
    """, (vendor_id,))
    vendor_reviews = cursor.fetchall()
    
    # Average rating across all vendor's products
    cursor.execute("""
        SELECT AVG(r.rating) as avg_rating, COUNT(*) as total_reviews
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        WHERE p.vendor_id = %s
    """, (vendor_id,))
    review_summary = cursor.fetchone()  
        # Low stock alert
    cursor.execute("""
        SELECT COUNT(*) as count FROM products 
        WHERE vendor_id = %s AND stock_quantity < 10 AND is_approved = 1
    """, (vendor_id,))
    low_stock_count = cursor.fetchone()['count']
    cursor.close()
    conn.close()
    
    return render_template('vendor/dashboard.html',
                         total_products=total_products,
                         approved_products=approved_products,
                         pending_products=pending_products,
                         total_orders=total_orders,
                         products=products,
                         recent_orders=recent_orders,
                         vendor_reviews=vendor_reviews,
                         review_summary=review_summary)

# ------------------ Service Center Dashboard ------------------
# ------------------ Service Center Dashboard ------------------
@app.route('/service_center/dashboard')
def service_center_dashboard():
    if 'user_id' not in session or session.get('role') != 'service_center':
        flash('Please login as a service center.', 'warning')
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_center_details WHERE user_id = %s", (center_id,))
    center = cursor.fetchone()
    
    # ---- Stats ----
    cursor.execute("SELECT COUNT(*) as total FROM service_bookings WHERE station_id = %s", (center_id,))
    total_bookings = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM service_bookings WHERE station_id = %s AND status = 'booked'", (center_id,))
    pending_bookings = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM service_bookings WHERE station_id = %s AND status = 'in_progress'", (center_id,))
    in_progress = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM service_bookings WHERE station_id = %s AND status = 'completed'", (center_id,))
    completed = cursor.fetchone()['total']
    
    # ---- Review stats ----
    cursor.execute("""
        SELECT AVG(rating) as avg_rating, COUNT(*) as review_count
        FROM reviews WHERE station_id = %s
    """, (center_id,))
    review_stats = cursor.fetchone()
    avg_rating = review_stats['avg_rating'] or 0
    review_count = review_stats['review_count'] or 0
    
    # Rating distribution
    cursor.execute("""
        SELECT rating, COUNT(*) as count FROM reviews 
        WHERE station_id = %s GROUP BY rating
    """, (center_id,))
    distribution_rows = cursor.fetchall()
    rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in distribution_rows:
        rating_distribution[row['rating']] = row['count']
    
    # ---- Latest 5 reviews ----
    cursor.execute("""
        SELECT r.*, u.name as customer_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.station_id = %s
        ORDER BY r.created_at DESC
        LIMIT 5
    """, (center_id,))
    latest_reviews = cursor.fetchall()
    
    # ---- Booking filters ----
    status_filter = request.args.get('status', 'all')
    date_filter = request.args.get('date', 'all')
    
    query = """
        SELECT sb.*, u.name as customer_name, u.phone as customer_phone, u.email as customer_email,
               v.make, v.model, v.registration_number, v.year as vehicle_year, v.fuel_type
        FROM service_bookings sb
        JOIN users u ON sb.customer_id = u.id
        JOIN vehicles v ON sb.vehicle_id = v.id
        WHERE sb.station_id = %s
    """
    params = [center_id]
    
    if status_filter != 'all':
        query += " AND sb.status = %s"
        params.append(status_filter)
    
    if date_filter == 'today':
        query += " AND DATE(sb.booking_date) = CURDATE()"
    elif date_filter == 'week':
        query += " AND sb.booking_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
    elif date_filter == 'month':
        query += " AND MONTH(sb.booking_date) = MONTH(CURDATE()) AND YEAR(sb.booking_date) = YEAR(CURDATE())"
    
    query += """
        ORDER BY 
            CASE sb.status 
                WHEN 'booked' THEN 1 
                WHEN 'in_progress' THEN 2 
                WHEN 'completed' THEN 3
                ELSE 4
            END,
            sb.booking_date DESC
    """
    
    cursor.execute(query, params)
    bookings = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('service_center/dashboard.html',
                         center=center,
                         total_bookings=total_bookings,
                         pending_bookings=pending_bookings,
                         in_progress=in_progress,
                         completed=completed,
                         avg_rating=avg_rating,
                         review_count=review_count,
                         rating_distribution=rating_distribution,
                         latest_reviews=latest_reviews,
                         bookings=bookings,
                         status_filter=status_filter,
                         date_filter=date_filter)


# ------------------ Service Center: Reviews Page ------------------
@app.route('/service_center/reviews')
def service_center_reviews():
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    rating_filter = request.args.get('rating', 'all')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_center_details WHERE user_id = %s", (center_id,))
    center = cursor.fetchone()
    
    # Stats
    cursor.execute("""
        SELECT AVG(rating) as avg_rating, COUNT(*) as review_count
        FROM reviews WHERE station_id = %s
    """, (center_id,))
    stats = cursor.fetchone()
    
    cursor.execute("""
        SELECT rating, COUNT(*) as count FROM reviews 
        WHERE station_id = %s GROUP BY rating
    """, (center_id,))
    dist_rows = cursor.fetchall()
    rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in dist_rows:
        rating_distribution[row['rating']] = row['count']
    
    # Filtered reviews list
    query = """
        SELECT r.*, u.name as customer_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.station_id = %s
    """
    params = [center_id]
    
    if rating_filter != 'all':
        query += " AND r.rating = %s"
        params.append(rating_filter)
    
    query += " ORDER BY r.created_at DESC"
    
    cursor.execute(query, params)
    reviews = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('service_center/reviews.html',
                         center=center,
                         stats=stats,
                         rating_distribution=rating_distribution,
                         reviews=reviews,
                         rating_filter=rating_filter)


# ------------------ Service Center: Maintenance History ------------------
# ------------------ Service Center: Maintenance History ------------------
@app.route('/service_center/maintenance')
def service_center_maintenance():
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    month_filter = request.args.get('month', 'all')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_center_details WHERE user_id = %s", (center_id,))
    center = cursor.fetchone()
    
    # ---- Maintenance records with optional month filter ----
    query = """
        SELECT mr.*, v.make, v.model, v.registration_number,
               u.name as customer_name, u.phone as customer_phone
        FROM maintenance_records mr
        JOIN vehicles v ON mr.vehicle_id = v.id
        JOIN users u ON v.user_id = u.id
        WHERE mr.performed_by_station_id = %s
    """
    params = [center_id]
    
    if month_filter != 'all':
        query += " AND CONCAT(YEAR(mr.created_at), '-', LPAD(MONTH(mr.created_at), 2, '0')) = %s"
        params.append(month_filter)
    
    query += " ORDER BY mr.created_at DESC"
    
    cursor.execute(query, params)
    records = cursor.fetchall()
    
    # ---- Stats ----
    cursor.execute("""
        SELECT COUNT(*) as total, COALESCE(SUM(cost), 0) as total_revenue
        FROM maintenance_records WHERE performed_by_station_id = %s
    """, (center_id,))
    stats = cursor.fetchone()
    
    # ---- Available months for filter (using %% for literal percent) ----
    cursor.execute("""
        SELECT DISTINCT DATE_FORMAT(created_at, '%%Y-%%m') as month
        FROM maintenance_records WHERE performed_by_station_id = %s
        ORDER BY month DESC
    """, (center_id,))
    available_months = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('service_center/maintenance.html',
                         center=center,
                         records=records,
                         stats=stats,
                         available_months=available_months,
                         month_filter=month_filter)
    
# ------------------ Service Center: Analytics ------------------
@app.route('/service_center/analytics')
def service_center_analytics():
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_center_details WHERE user_id = %s", (center_id,))
    center = cursor.fetchone()
    
    # Overall stats
    cursor.execute("""
        SELECT COUNT(*) as total_services, COALESCE(SUM(cost), 0) as total_revenue,
               COALESCE(AVG(cost), 0) as avg_cost
        FROM maintenance_records WHERE performed_by_station_id = %s
    """, (center_id,))
    overall = cursor.fetchone()
    
    # Monthly revenue (last 6 months) — NOTE: %% used for literal % in DATE_FORMAT
    cursor.execute("""
        SELECT DATE_FORMAT(created_at, '%%b %%Y') as month,
               DATE_FORMAT(created_at, '%%Y-%%m') as sort_key,
               COUNT(*) as services, COALESCE(SUM(cost), 0) as revenue
        FROM maintenance_records 
        WHERE performed_by_station_id = %s 
          AND created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
        GROUP BY sort_key, month
        ORDER BY sort_key
    """, (center_id,))
    monthly = cursor.fetchall()
    
    # Service type distribution
    cursor.execute("""
        SELECT service_type, COUNT(*) as count, COALESCE(SUM(cost), 0) as revenue
        FROM maintenance_records 
        WHERE performed_by_station_id = %s AND service_type IS NOT NULL
        GROUP BY service_type
        ORDER BY count DESC
        LIMIT 6
    """, (center_id,))
    service_types = cursor.fetchall()
    
    # Recent completions
    cursor.execute("""
        SELECT mr.*, v.make, v.model, u.name as customer_name
        FROM maintenance_records mr
        JOIN vehicles v ON mr.vehicle_id = v.id
        JOIN users u ON v.user_id = u.id
        WHERE mr.performed_by_station_id = %s
        ORDER BY mr.created_at DESC
        LIMIT 10
    """, (center_id,))
    recent = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('service_center/analytics.html',
                         center=center,
                         overall=overall,
                         monthly=monthly,
                         service_types=service_types,
                         recent=recent)

# ------------------ Service Center: Booking Action ------------------
@app.route('/service_center/booking/<int:booking_id>/<action>')
def service_center_booking_action(booking_id, action):
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_bookings WHERE id = %s AND station_id = %s", (booking_id, center_id))
    booking = cursor.fetchone()
    
    if not booking:
        cursor.close()
        conn.close()
        flash('Booking not found.', 'danger')
        return redirect(url_for('service_center_dashboard'))
    
    if action == 'start':
        cursor.execute("UPDATE service_bookings SET status = 'in_progress' WHERE id = %s", (booking_id,))
        flash('Booking marked as in progress.', 'success')
    elif action == 'complete':
        cursor.execute("UPDATE service_bookings SET status = 'completed' WHERE id = %s", (booking_id,))
        flash('Booking completed!', 'success')
    elif action == 'cancel':
        cursor.execute("UPDATE service_bookings SET status = 'cancelled' WHERE id = %s", (booking_id,))
        flash('Booking cancelled.', 'info')
    
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('service_center_dashboard'))


# ------------------ Service Center: Add Maintenance Record ------------------
@app.route('/service_center/booking/<int:booking_id>/add-maintenance', methods=['POST'])
def service_center_add_maintenance(booking_id):
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    center_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM service_bookings WHERE id = %s AND station_id = %s", (booking_id, center_id))
    booking = cursor.fetchone()
    
    if not booking:
        cursor.close()
        conn.close()
        flash('Booking not found.', 'danger')
        return redirect(url_for('service_center_dashboard'))
    
    service_type = request.form.get('service_type')
    description = request.form.get('description')
    mileage = request.form.get('mileage_km') or None
    cost = request.form.get('cost') or None
    next_due_date = request.form.get('next_due_date') or None
    next_due_mileage = request.form.get('next_due_mileage_km') or None
    
    cursor.execute("""
        INSERT INTO maintenance_records 
        (vehicle_id, service_type, description, mileage_km, next_due_mileage_km, next_due_date, performed_by_station_id, cost)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (booking['vehicle_id'], service_type, description, mileage, next_due_mileage, next_due_date, center_id, cost))
    
    cursor.execute("UPDATE service_bookings SET status = 'completed' WHERE id = %s", (booking_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Maintenance record added and booking completed!', 'success')
    return redirect(url_for('service_center_dashboard'))


# ------------------ Service Center Profile ------------------
@app.route('/service_center/profile', methods=['GET', 'POST'])
def service_center_profile():
    if 'user_id' not in session or session.get('role') != 'service_center':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        center_name = request.form.get('center_name')
        address = request.form.get('address')
        city = request.form.get('city')
        pincode = request.form.get('pincode')
        specialization = request.form.get('specialization')
        open_time = request.form.get('open_time')
        close_time = request.form.get('close_time')
        
        cursor.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s", (name, phone, session['user_id']))
        cursor.execute("""
            UPDATE service_center_details 
            SET center_name=%s, address=%s, city=%s, pincode=%s, specialization=%s, open_time=%s, close_time=%s 
            WHERE user_id=%s
        """, (center_name, address, city, pincode, specialization, open_time, close_time, session['user_id']))
        conn.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('service_center_profile'))
    
    cursor.execute("""
        SELECT u.*, sc.center_name, sc.address, sc.city, sc.pincode, sc.specialization,
               sc.open_time, sc.close_time, sc.is_approved
        FROM users u
        JOIN service_center_details sc ON u.id = sc.user_id
        WHERE u.id = %s
    """, (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template('service_center/profile.html', user=user)


# ==================== ADMIN DASHBOARD ====================
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Please login as an admin.', 'warning')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total counts
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'customer'")
    total_customers = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'vendor'")
    total_vendors = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'service_center'")
    total_service_centers = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM vendor_details WHERE is_approved = 0")
    pending_vendors = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM service_center_details WHERE is_approved = 0")
    pending_centers = cursor.fetchone()['total']
    
    # Total products and orders
    cursor.execute("SELECT COUNT(*) as total FROM products")
    total_products = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM orders")
    total_orders = cursor.fetchone()['total']
    
    # Revenue (total sales)
    cursor.execute("SELECT COALESCE(SUM(total_amount), 0) as total FROM orders WHERE order_status = 'delivered'")
    total_revenue = cursor.fetchone()['total']
    
    # Recent orders
    cursor.execute("""
        SELECT o.*, u.name as customer_name, u.email as customer_email 
        FROM orders o 
        JOIN users u ON o.customer_id = u.id 
        ORDER BY o.created_at DESC 
        LIMIT 10
    """)
    recent_orders = cursor.fetchall()
    
    # Sales by category (for chart)
    cursor.execute("""
        SELECT pc.name as category, COUNT(p.id) as count, COALESCE(SUM(oi.quantity * oi.price_per_unit), 0) as revenue
        FROM product_categories pc
        LEFT JOIN products p ON pc.id = p.category_id
        LEFT JOIN order_items oi ON p.id = oi.product_id
        GROUP BY pc.id, pc.name
        ORDER BY revenue DESC
    """)
    sales_by_category = cursor.fetchall()
    
    # Monthly sales (last 6 months for chart)
    cursor.execute("""
        SELECT 
            DATE_FORMAT(created_at, '%b %Y') as month,
            COUNT(*) as orders_count,
            COALESCE(SUM(total_amount), 0) as revenue
        FROM orders 
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
        GROUP BY DATE_FORMAT(created_at, '%Y-%m'), DATE_FORMAT(created_at, '%b %Y')
        ORDER BY MIN(created_at)
    """)
    monthly_sales = cursor.fetchall()
    
    # Top vendors by sales
    cursor.execute("""
        SELECT u.name as vendor_name, vd.business_name, COUNT(o.id) as total_orders, 
               COALESCE(SUM(oi.quantity * oi.price_per_unit), 0) as revenue
        FROM users u
        JOIN vendor_details vd ON u.id = vd.user_id
        LEFT JOIN products p ON u.id = p.vendor_id
        LEFT JOIN order_items oi ON p.id = oi.product_id
        LEFT JOIN orders o ON oi.order_id = o.id
        WHERE u.role = 'vendor'
        GROUP BY u.id, u.name, vd.business_name
        ORDER BY revenue DESC
        LIMIT 5
    """)
    top_vendors = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('admin/dashboard.html',
                         total_customers=total_customers,
                         total_vendors=total_vendors,
                         total_service_centers=total_service_centers,
                         pending_vendors=pending_vendors,
                         pending_centers=pending_centers,
                         total_products=total_products,
                         total_orders=total_orders,
                         total_revenue=total_revenue,
                         recent_orders=recent_orders,
                         sales_by_category=sales_by_category,
                         monthly_sales=monthly_sales,
                         top_vendors=top_vendors)

# ==================== MANAGE USERS ====================
@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, email, role, name, phone, is_verified, created_at 
        FROM users 
        ORDER BY created_at DESC
    """)
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/manage_users.html', users=users)

# ==================== MANAGE VENDORS ====================
@app.route('/admin/vendors')
def admin_vendors():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.phone, u.created_at,
               vd.business_name, vd.gst_number, vd.city, vd.is_approved,
               (SELECT COUNT(*) FROM products WHERE vendor_id = u.id) as product_count
        FROM users u
        JOIN vendor_details vd ON u.id = vd.user_id
        WHERE u.role = 'vendor'
        ORDER BY u.created_at DESC
    """)
    vendors = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/verify_vendors.html', vendors=vendors)

# ==================== APPROVE/REJECT VENDOR ====================
@app.route('/admin/vendor/<int:vendor_id>/<action>')
def admin_vendor_action(vendor_id, action):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if action == 'approve':
        cursor.execute("UPDATE vendor_details SET is_approved = 1 WHERE user_id = %s", (vendor_id,))
        cursor.execute("UPDATE users SET is_verified = 1 WHERE id = %s AND role = 'vendor'", (vendor_id,))
        flash('Vendor approved successfully!', 'success')
                # Send approval email
        try:
            cursor.execute("SELECT email, name FROM users WHERE id = %s", (vendor_id,))
            v = cursor.fetchone()
            if v and v['email']:
                body = f"""
                <div style="font-family:Arial,sans-serif; padding:20px;">
                    <h2 style="color:#146c43;">Welcome to PartMatch! 🎉</h2>
                    <p>Hi {v['name']},</p>
                    <p>Your vendor account has been <strong>approved</strong>. You can now log in and start listing products.</p>
                    <a href="http://localhost:5000/" style="display:inline-block; padding:12px 24px; background:#146c43; color:#fff; text-decoration:none; border-radius:8px;">Log In Now</a>
                </div>
                """
                send_email(v['email'], 'Vendor Account Approved — PartMatch', body)
        except Exception as e:
            print(f"Email error: {e}")
    elif action == 'reject':
        cursor.execute("DELETE FROM vendor_details WHERE user_id = %s", (vendor_id,))
        cursor.execute("DELETE FROM users WHERE id = %s AND role = 'vendor'", (vendor_id,))
        flash('Vendor rejected and removed.', 'danger')
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_vendors'))

# ==================== MANAGE SERVICE CENTERS ====================
# ==================== MANAGE SERVICE CENTERS ====================
@app.route('/admin/service-centers')
def admin_service_centers():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.phone, u.created_at,
               sc.center_name, sc.center_name as business_name,
               sc.registration_number as gst_number,
               sc.city, sc.specialization, sc.is_approved
        FROM users u
        JOIN service_center_details sc ON u.id = sc.user_id
        WHERE u.role = 'service_center'
        ORDER BY u.created_at DESC
    """)
    centers = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/manage_service_centers.html', service_centers=centers)

# ==================== APPROVE/REJECT SERVICE CENTER ====================
# ==================== APPROVE/REJECT SERVICE CENTER ====================
@app.route('/admin/service-center/<int:service_center_id>/<action>')
def admin_service_center_action(service_center_id, action):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if action == 'approve':
        cursor.execute("UPDATE service_center_details SET is_approved = 1 WHERE user_id = %s", (service_center_id,))
        cursor.execute("UPDATE users SET is_verified = 1 WHERE id = %s AND role = 'service_center'", (service_center_id,))
        flash('Service center approved successfully!', 'success')
    elif action == 'reject':
        cursor.execute("DELETE FROM service_center_details WHERE user_id = %s", (service_center_id,))
        cursor.execute("DELETE FROM users WHERE id = %s AND role = 'service_center'", (service_center_id,))
        flash('Service center removed.', 'danger')
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_service_centers'))

# ==================== APPROVE PRODUCTS ====================
@app.route('/admin/products')
def admin_products():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, u.name as vendor_name, pc.name as category_name
        FROM products p
        JOIN users u ON p.vendor_id = u.id
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        ORDER BY p.created_at DESC
    """)
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/approve_products.html', products=products)

@app.route('/admin/product/<int:product_id>/<action>')
def admin_product_action(product_id, action):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if action == 'approve':
        cursor.execute("UPDATE products SET is_approved = 1 WHERE id = %s", (product_id,))
        flash('Product approved!', 'success')
    elif action == 'reject':
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        flash('Product rejected and removed.', 'danger')
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_products'))

# ==================== REPORTS ====================
@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Revenue by month
    cursor.execute("""
        SELECT DATE_FORMAT(created_at, '%Y-%m') as month,
               COUNT(*) as orders, SUM(total_amount) as revenue
        FROM orders GROUP BY DATE_FORMAT(created_at, '%Y-%m')
        ORDER BY month DESC LIMIT 12
    """)
    monthly_data = cursor.fetchall()
    
    # Orders by status
    cursor.execute("""
        SELECT order_status, COUNT(*) as count FROM orders GROUP BY order_status
    """)
    order_status = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('admin/reports.html', monthly_data=monthly_data, order_status=order_status)

# ==================== DEBUG ROUTES ====================

# Test 1: Check if admin exists in database
@app.route('/debug/check-admin')
def debug_check_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, role, password_hash FROM users WHERE email = 'admin@partmatch.com'")
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not user:
        return "<h1>❌ Admin NOT FOUND in database!</h1>"
    
    test = check_password_hash(user['password_hash'], 'admin123')
    return f"""
    <h2>Admin found:</h2>
    <p>ID: {user['id']}</p>
    <p>Email: {user['email']}</p>
    <p>Role: {user['role']}</p>
    <p>Password 'admin123' matches: <b>{test}</b></p>
    """

# Test 2: Direct login without modal
@app.route('/debug/direct-login')
def debug_direct_login():
    return '''
    <h2>Direct Login Test</h2>
    <form method="post" action="/login">
        <input type="text" name="loginEmail" value="admin@partmatch.com"><br><br>
        <input type="password" name="loginPass" value="admin123"><br><br>
        <button type="submit">LOGIN</button>
    </form>
    '''

# Test 3: Check session
@app.route('/debug/session')
def debug_session():
    return f"""
    <h2>Session Data</h2>
    <p>user_id: {session.get('user_id', 'NOT SET')}</p>
    <p>role: {session.get('role', 'NOT SET')}</p>
    <p>user_name: {session.get('user_name', 'NOT SET')}</p>
    """
   
# ------------------ Vendor: Add Product ------------------

@app.route('/vendor/add-product', methods=['GET', 'POST'])
def vendor_add_product():
    if 'user_id' not in session or session.get('role') != 'vendor':
        flash('Please login as a vendor.', 'warning')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM product_categories ORDER BY name")
    categories = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if request.method == 'POST':
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        brand = request.form.get('brand')
        part_number = request.form.get('part_number')
        price = request.form.get('price')
        stock = request.form.get('stock_quantity')
        description = request.form.get('description')
        compatibility = request.form.get('compatibility')
        
        # ----- IMAGE UPLOAD -----
        image_filename = None
        if 'product_image' in request.files:
            file = request.files['product_image']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                # Unique filename: vendorId_timestamp.ext
                image_filename = f"vendor{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO products (vendor_id, category_id, name, description, brand, part_number, price, stock_quantity, compatibility, image)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (session['user_id'], category_id, name, description, brand, part_number, price, stock, compatibility, image_filename))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Product added! Waiting for admin approval.', 'success')
        return redirect(url_for('vendor_dashboard'))
    
    return render_template('vendor/add_product.html', categories=categories)


# ------------------ Vendor: Manage Inventory ------------------
@app.route('/vendor/inventory')
def vendor_manage_inventory():
    if 'user_id' not in session or session.get('role') != 'vendor':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, pc.name as category_name 
        FROM products p 
        LEFT JOIN product_categories pc ON p.category_id = pc.id 
        WHERE p.vendor_id = %s 
        ORDER BY p.created_at DESC
    """, (session['user_id'],))
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('vendor/manage_inventory.html', products=products)

# ------------------ Vendor: Orders ------------------
@app.route('/vendor/orders')
def vendor_orders():
    if 'user_id' not in session or session.get('role') != 'vendor':
        flash('Please login as a vendor.', 'warning')
        return redirect(url_for('home'))
    
    vendor_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all orders containing this vendor's products
    cursor.execute("""
        SELECT DISTINCT o.id, o.order_status, o.total_amount, o.shipping_address, o.created_at,
               u.name as customer_name, u.email as customer_email, u.phone as customer_phone
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        JOIN users u ON o.customer_id = u.id
        WHERE p.vendor_id = %s
        ORDER BY o.created_at DESC
    """, (vendor_id,))
    orders = cursor.fetchall()
    
    # For each order, fetch ONLY this vendor's items
    for order in orders:
        cursor.execute("""
            SELECT oi.id, oi.quantity, oi.price_per_unit,
                   p.name as product_name, p.brand, p.image, p.part_number
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s AND p.vendor_id = %s
        """, (order['id'], vendor_id))
        order['vendor_items'] = cursor.fetchall()
        
        # Calculate vendor's subtotal (only their items)
        order['vendor_subtotal'] = sum(
            float(item['quantity']) * float(item['price_per_unit']) 
            for item in order['vendor_items']
        )
        order['item_count'] = len(order['vendor_items'])
    
    # Stats
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT CASE WHEN o.order_status = 'confirmed' THEN o.id END) as pending_count,
            COUNT(DISTINCT CASE WHEN o.order_status = 'shipped' THEN o.id END) as shipped_count,
            COUNT(DISTINCT CASE WHEN o.order_status = 'delivered' THEN o.order_status END) as delivered_count
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE p.vendor_id = %s
    """, (vendor_id,))
    stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('vendor/orders.html',
                         orders=orders,
                         pending_count=stats['pending_count'] or 0,
                         shipped_count=stats['shipped_count'] or 0,
                         delivered_count=stats['delivered_count'] or 0)

# ------------------ Vendor: Update Order Status ------------------
@app.route('/vendor/order/<int:order_id>/<action>', methods=['POST'])
def vendor_update_order_status(order_id, action):
    if 'user_id' not in session or session.get('role') != 'vendor':
        flash('Please login as a vendor.', 'warning')
        return redirect(url_for('home'))
    
    vendor_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify this vendor has items in the order
    cursor.execute("""
        SELECT COUNT(*) as count FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s AND p.vendor_id = %s
    """, (order_id, vendor_id))
    check = cursor.fetchone()
    
    if not check or check['count'] == 0:
        cursor.close()
        conn.close()
        flash('Order not found or does not belong to your store.', 'danger')
        return redirect(url_for('vendor_orders'))
    
    # Update based on action
    status_map = {
        'confirm': 'confirmed',
        'ship': 'shipped',
        'deliver': 'delivered',
    }
    
    if action in status_map:
        new_status = status_map[action]
        cursor.execute("UPDATE orders SET order_status = %s WHERE id = %s", (new_status, order_id))
        conn.commit()
        flash(f'Order #{order_id} marked as {new_status}.', 'success')
        
        # Notify customer via email
        try:
            cursor.execute("""
                SELECT u.email, u.name FROM orders o
                JOIN users u ON o.customer_id = u.id WHERE o.id = %s
            """, (order_id,))
            cust = cursor.fetchone()
            if cust and cust['email']:
                status_msg = {
                    'confirmed': 'Your order has been confirmed by the vendor.',
                    'shipped': 'Your order has been shipped!',
                    'delivered': 'Your order has been delivered. Enjoy!',
                }.get(new_status, '')
                body = f"""
                <div style="font-family:Arial,sans-serif; padding:20px;">
                    <h2 style="color:#146c43;">Order Update 📦</h2>
                    <p>Hi {cust['name']},</p>
                    <p>Order <strong>#{order_id}</strong> is now <strong>{new_status.upper()}</strong>.</p>
                    <p>{status_msg}</p>
                    <a href="http://localhost:5000/customer/orders" style="display:inline-block; padding:12px 24px; background:#146c43; color:#fff; text-decoration:none; border-radius:8px;">View Order</a>
                </div>
                """
                send_email(cust['email'], f'Order #{order_id} — {new_status.title()} — PartMatch', body)
        except Exception as e:
            print(f"Email error: {e}")
    else:
        flash('Invalid action.', 'danger')
    
    cursor.close()
    conn.close()
    return redirect(url_for('vendor_orders'))

# ------------------ Vendor: Edit Product ------------------
@app.route('/vendor/edit-product/<int:product_id>', methods=['GET', 'POST'])
def vendor_edit_product(product_id):
    if 'user_id' not in session or session.get('role') != 'vendor':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        brand = request.form.get('brand')
        part_number = request.form.get('part_number')
        price = request.form.get('price')
        stock = request.form.get('stock_quantity')
        description = request.form.get('description')
        
        cursor.execute("""
            UPDATE products 
            SET name=%s, category_id=%s, brand=%s, part_number=%s, price=%s, stock_quantity=%s, description=%s 
            WHERE id=%s AND vendor_id=%s
        """, (name, category_id, brand, part_number, price, stock, description, product_id, session['user_id']))
        conn.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('vendor_manage_inventory'))
    
    cursor.execute("SELECT * FROM products WHERE id = %s AND vendor_id = %s", (product_id, session['user_id']))
    product = cursor.fetchone()
    
    cursor.execute("SELECT * FROM product_categories ORDER BY name")
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('vendor_manage_inventory'))
    
    return render_template('vendor/edit_product.html', product=product, categories=categories)

# ------------------ Vendor: Delete Product ------------------
@app.route('/vendor/delete-product/<int:product_id>')
def vendor_delete_product(product_id):
    if 'user_id' not in session or session.get('role') != 'vendor':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = %s AND vendor_id = %s", (product_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Product deleted.', 'info')
    return redirect(url_for('vendor_manage_inventory'))

# ------------------ Customer Profile ------------------
@app.route('/customer/profile', methods=['GET', 'POST'])
def customer_profile():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        cursor.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s", (name, phone, session['user_id']))
        conn.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('customer_profile'))
    
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    # Get user's vehicles
    cursor.execute("SELECT * FROM vehicles WHERE user_id = %s", (session['user_id'],))
    vehicles = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/profile.html', user=user, vehicles=vehicles)

# ------------------ Vendor Profile ------------------
@app.route('/vendor/profile', methods=['GET', 'POST'])
def vendor_profile():
    if 'user_id' not in session or session.get('role') != 'vendor':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        business_name = request.form.get('business_name')
        gst = request.form.get('gst_number')
        city = request.form.get('city')
        address = request.form.get('address')
        
        cursor.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s", (name, phone, session['user_id']))
        cursor.execute("UPDATE vendor_details SET business_name=%s, gst_number=%s, city=%s, address=%s WHERE user_id=%s", 
                      (business_name, gst, city, address, session['user_id']))
        conn.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('vendor_profile'))
    
    cursor.execute("""
        SELECT u.*, vd.business_name, vd.gst_number, vd.city, vd.address, vd.is_approved
        FROM users u
        JOIN vendor_details vd ON u.id = vd.user_id
        WHERE u.id = %s
    """, (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template('vendor/profile.html', user=user)

# ------------------ Admin Profile ------------------
@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        new_password = request.form.get('new_password')
        
        if new_password:
            hashed = generate_password_hash(new_password)
            cursor.execute("UPDATE users SET name=%s, phone=%s, password_hash=%s WHERE id=%s", 
                          (name, phone, hashed, session['user_id']))
        else:
            cursor.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s", 
                          (name, phone, session['user_id']))
        conn.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('admin_profile'))
    
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template('admin/profile.html', user=user)

# ------------------ Customer: My Vehicles ------------------
@app.route('/customer/vehicles', methods=['GET', 'POST'])
def customer_vehicles():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        make = request.form.get('make')
        model = request.form.get('model')
        variant = request.form.get('variant')
        fuel_type = request.form.get('fuel_type')
        year = request.form.get('year')
        reg_number = request.form.get('registration_number')
        vin = request.form.get('vin')
        
        cursor.execute("""
            INSERT INTO vehicles (user_id, make, model, variant, fuel_type, year, registration_number, vin)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (customer_id, make, model, variant, fuel_type, year, reg_number, vin or None))
        conn.commit()
        flash('Vehicle registered successfully!', 'success')
        return redirect(url_for('customer_vehicles'))
    
    # Get all vehicles for this user
    cursor.execute("SELECT * FROM vehicles WHERE user_id = %s ORDER BY created_at DESC", (customer_id,))
    vehicles = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/register_vehicle.html', vehicles=vehicles)

# ------------------ Customer: Delete Vehicle ------------------
@app.route('/customer/vehicle/<int:vehicle_id>/delete')
def customer_delete_vehicle(vehicle_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vehicles WHERE id = %s AND user_id = %s", (vehicle_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Vehicle removed.', 'info')
    return redirect(url_for('customer_vehicles'))

@app.route('/customer/search')
def customer_search_parts():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    search = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', 'newest')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM product_categories ORDER BY name")
    categories = cursor.fetchall()
    
    cursor.execute("SELECT make, model FROM vehicles WHERE user_id = %s", (customer_id,))
    user_vehicles = cursor.fetchall()
    
    query = """
        SELECT p.*, 
               pc.name as category_name,
               u.name as vendor_name,
               vd.business_name,
               (SELECT AVG(rating) FROM reviews WHERE product_id = p.id) as avg_rating,
               (SELECT COUNT(*) FROM reviews WHERE product_id = p.id) as review_count
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        JOIN users u ON p.vendor_id = u.id
        LEFT JOIN vendor_details vd ON u.id = vd.user_id
        WHERE p.is_approved = 1 AND p.stock_quantity > 0
    """
    params = []
    
    if search:
        query += " AND (p.name LIKE %s OR p.brand LIKE %s OR p.part_number LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    
    if category_filter:
        query += " AND p.category_id = %s"
        params.append(category_filter)
    
    # Sort options
    if sort_by == 'price_low':
        query += " ORDER BY p.price ASC"
    elif sort_by == 'price_high':
        query += " ORDER BY p.price DESC"
    elif sort_by == 'rating':
        query += " ORDER BY avg_rating DESC, review_count DESC"
    elif sort_by == 'oldest':
        query += " ORDER BY p.created_at ASC"
    else:  # newest
        query += " ORDER BY p.created_at DESC"
    
    cursor.execute(query, params)
    products = cursor.fetchall()
    
    for product in products:
        product['is_compatible'] = check_compatibility(product.get('compatibility'), user_vehicles)
    
    cursor.close()
    conn.close()
    
    return render_template('customer/search_parts.html',
                         products=products,
                         categories=categories,
                         search=search,
                         category_filter=category_filter,
                         sort_by=sort_by,
                         vehicle_count=len(user_vehicles))
    

# ------------------ Customer: Search Suggestions API ------------------
@app.route('/customer/api/search-suggestions')
def customer_search_suggestions():
    if 'user_id' not in session or session.get('role') != 'customer':
        return {'suggestions': []}
    
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return {'suggestions': []}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    like = f"%{q}%"
    cursor.execute("""
        SELECT DISTINCT name, brand FROM products 
        WHERE is_approved = 1 AND stock_quantity > 0 
          AND (name LIKE %s OR brand LIKE %s)
        LIMIT 8
    """, (like, like))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    suggestions = []
    seen = set()
    for row in rows:
        if row['name'] and row['name'] not in seen:
            suggestions.append(row['name'])
            seen.add(row['name'])
        if row['brand'] and row['brand'] not in seen:
            suggestions.append(row['brand'])
            seen.add(row['brand'])
    
    return {'suggestions': suggestions[:8]}

# ------------------ Customer: Product Detail ------------------
@app.route('/customer/product/<int:product_id>')
def customer_product_detail(product_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT p.*, 
               pc.name as category_name,
               u.name as vendor_name,
               u.phone as vendor_phone,
               u.email as vendor_email,
               vd.business_name,
               vd.city as vendor_city,
               vd.address as vendor_address
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        JOIN users u ON p.vendor_id = u.id
        LEFT JOIN vendor_details vd ON u.id = vd.user_id
        WHERE p.id = %s AND p.is_approved = 1
    """, (product_id,))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        conn.close()
        flash('Product not found or not yet approved.', 'warning')
        return redirect(url_for('customer_search_parts'))
    
    # Check compatibility
    cursor.execute("SELECT make, model FROM vehicles WHERE user_id = %s", (customer_id,))
    user_vehicles = cursor.fetchall()
    product['is_compatible'] = check_compatibility(product.get('compatibility'), user_vehicles)
    
    # Parse compatibility JSON for display
    try:
        compat = json.loads(product['compatibility']) if product.get('compatibility') else {}
    except:
        compat = {}
    
    # Related products from same category
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.image, p.brand
        FROM products p
        WHERE p.category_id = %s AND p.id != %s AND p.is_approved = 1 AND p.stock_quantity > 0
        LIMIT 4
    """, (product['category_id'], product_id))
    related_products = cursor.fetchall()
    
    # Fetch reviews for this product
    cursor.execute("""
        SELECT r.*, u.name as user_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.product_id = %s
        ORDER BY r.created_at DESC
    """, (product_id,))
    reviews = cursor.fetchall()
    
    # Average rating
    cursor.execute("""
        SELECT AVG(rating) as avg_rating, COUNT(*) as review_count
        FROM reviews WHERE product_id = %s
    """, (product_id,))
    rating_info = cursor.fetchone()
    
    # Check if this customer can review (purchased + delivered)
    cursor.execute("""
        SELECT COUNT(*) as count FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        WHERE o.customer_id = %s AND oi.product_id = %s AND o.order_status = 'delivered'
    """, (customer_id, product_id))
    can_review = cursor.fetchone()['count'] > 0
    
    # Check if already reviewed
    cursor.execute("SELECT * FROM reviews WHERE user_id = %s AND product_id = %s", (customer_id, product_id))
    my_review = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/product_detail.html',
                         product=product,
                         compat=compat,
                         related_products=related_products,
                         vehicle_count=len(user_vehicles),
                         reviews=reviews,
                         rating_info=rating_info,
                         can_review=can_review,
                         my_review=my_review)

# ------------------ Customer: Bookings ------------------
# ------------------ Customer: Bookings ------------------
@app.route('/customer/bookings', methods=['GET', 'POST'])
def customer_bookings():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        station_id = request.form.get('station_id')
        vehicle_id = request.form.get('vehicle_id')
        booking_date = request.form.get('booking_date')
        time_slot = request.form.get('time_slot')
        service_type = request.form.get('service_type')
        notes = request.form.get('notes')
        
        if not station_id or not vehicle_id or not booking_date or not time_slot:
            flash('Please fill all required fields.', 'danger')
            return redirect(url_for('customer_bookings'))
        
        cursor.execute("""
            INSERT INTO service_bookings (customer_id, vehicle_id, station_id, booking_date, time_slot, service_type, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s, 'booked', %s)
        """, (customer_id, vehicle_id, station_id, booking_date, time_slot, service_type, notes))
        conn.commit()
        flash('Service appointment booked successfully!', 'success')
        return redirect(url_for('customer_bookings'))
    
    # Get approved service centers
        # Get approved service centers WITH ratings
    cursor.execute("""
        SELECT sc.user_id as id, sc.center_name, sc.address, sc.city, sc.specialization,
               sc.open_time, sc.close_time, u.phone, u.email,
               (SELECT AVG(rating) FROM reviews WHERE station_id = sc.user_id) as avg_rating,
               (SELECT COUNT(*) FROM reviews WHERE station_id = sc.user_id) as review_count
        FROM service_center_details sc
        JOIN users u ON sc.user_id = u.id
        WHERE sc.is_approved = 1
        ORDER BY sc.center_name
    """)
    service_centers = cursor.fetchall()
    
    # Get customer's vehicles
    cursor.execute("SELECT * FROM vehicles WHERE user_id = %s", (customer_id,))
    vehicles = cursor.fetchall()
    
    # Get customer's bookings
    cursor.execute("""
        SELECT sb.*, sc.center_name, sc.city,
               v.make, v.model, v.registration_number
        FROM service_bookings sb
        JOIN service_center_details sc ON sb.station_id = sc.user_id
        JOIN vehicles v ON sb.vehicle_id = v.id
        WHERE sb.customer_id = %s
        ORDER BY sb.booking_date DESC, sb.id DESC
    """, (customer_id,))
    bookings = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/bookings.html',
                         service_centers=service_centers,
                         vehicles=vehicles,
                         bookings=bookings)

# ==================== CUSTOMER: CART ====================

@app.before_request
def ensure_cart_exists():
    """Ensure a cart exists in the session"""
    if 'user_id' in session and session.get('role') == 'customer':
        if 'cart' not in session:
            session['cart'] = []


@app.route('/customer/cart')
def customer_cart():
    """View cart page"""
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    cart = session.get('cart', [])
    cart_items = []
    subtotal = 0
    
    if cart:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for item in cart:
            cursor.execute("""
                SELECT p.*, u.name as vendor_name, vd.business_name
                FROM products p
                JOIN users u ON p.vendor_id = u.id
                LEFT JOIN vendor_details vd ON u.id = vd.user_id
                WHERE p.id = %s AND p.is_approved = 1
            """, (item['product_id'],))
            product = cursor.fetchone()
            
            if product:
                item_total = float(product['price']) * item['quantity']
                subtotal += item_total
                cart_items.append({
                    'product': product,
                    'quantity': item['quantity'],
                    'item_total': item_total
                })
        
        cursor.close()
        conn.close()
    
    return render_template('customer/cart.html',
                         cart_items=cart_items,
                         subtotal=subtotal)


@app.route('/customer/add-to-cart/<int:product_id>', methods=['POST'])
def customer_add_to_cart(product_id):
    """Add product to cart"""
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    quantity = int(request.form.get('quantity', 1))
    
    # Verify product exists and is approved
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, stock_quantity FROM products WHERE id = %s AND is_approved = 1", (product_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('customer_search_parts'))
    
    if product['stock_quantity'] < quantity:
        flash('Not enough stock available.', 'warning')
        return redirect(url_for('customer_product_detail', product_id=product_id))
    
    cart = session.get('cart', [])
    product_exists = False
    
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            product_exists = True
            break
    
    if not product_exists:
        cart.append({'product_id': product_id, 'quantity': quantity})
    
    session['cart'] = cart
    session.modified = True
    
    flash('Item added to cart!', 'success')
    return redirect(url_for('customer_cart'))


@app.route('/customer/cart/update/<int:product_id>', methods=['POST'])
def customer_cart_update(product_id):
    """Update quantity in cart"""
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('home'))
    
    new_qty = int(request.form.get('quantity', 1))
    cart = session.get('cart', [])
    
    if new_qty <= 0:
        cart = [item for item in cart if item['product_id'] != product_id]
    else:
        for item in cart:
            if item['product_id'] == product_id:
                item['quantity'] = new_qty
                break
    
    session['cart'] = cart
    session.modified = True
    flash('Cart updated.', 'success')
    return redirect(url_for('customer_cart'))


@app.route('/customer/cart/remove/<int:product_id>')
def customer_cart_remove(product_id):
    """Remove item from cart"""
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('home'))
    
    cart = session.get('cart', [])
    cart = [item for item in cart if item['product_id'] != product_id]
    session['cart'] = cart
    session.modified = True
    
    flash('Item removed from cart.', 'info')
    return redirect(url_for('customer_cart'))


# ==================== CUSTOMER: CHECKOUT ====================

@app.route('/customer/checkout', methods=['GET'])
def customer_checkout():
    """Checkout page - shows cart and creates Razorpay order"""
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    cart = session.get('cart', [])
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('customer_cart'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Load cart items from DB
    cart_items = []
    subtotal = 0
    for item in cart:
        cursor.execute("""
            SELECT p.*, u.name as vendor_name, vd.business_name
            FROM products p
            JOIN users u ON p.vendor_id = u.id
            LEFT JOIN vendor_details vd ON u.id = vd.user_id
            WHERE p.id = %s AND p.is_approved = 1
        """, (item['product_id'],))
        product = cursor.fetchone()
        if product:
            item_total = float(product['price']) * item['quantity']
            subtotal += item_total
            cart_items.append({
                'product': product,
                'quantity': item['quantity'],
                'item_total': item_total
            })
    
    cursor.execute("SELECT name, phone FROM users WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    # Create Razorpay order
    amount_in_paise = int(subtotal * 100)   # Razorpay uses paise
    razorpay_order = razorpay_client.order.create({
        'amount': amount_in_paise,
        'currency': 'INR',
        'receipt': f'order_rcptid_{customer_id}_{int(datetime.now().timestamp())}',
        'notes': {
            'customer_id': customer_id,
            'customer_name': customer['name']
        }
    })
    
    return render_template('customer/checkout.html',
                         cart_items=cart_items,
                         subtotal=subtotal,
                         customer=customer,
                         razorpay_order_id=razorpay_order['id'],
                         razorpay_key_id=RAZORPAY_KEY_ID,
                         amount_in_paise=amount_in_paise)
    

@app.route('/customer/verify-payment', methods=['POST'])
def customer_verify_payment():
    """Verify Razorpay signature and save the order"""
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    # Get payment details from Razorpay response
    payment_id = request.form.get('razorpay_payment_id')
    order_id = request.form.get('razorpay_order_id')
    signature = request.form.get('razorpay_signature')
    shipping_address = request.form.get('shipping_address')
    
    customer_id = session['user_id']
    cart = session.get('cart', [])
    
    if not cart:
        flash('Cart is empty.', 'warning')
        return redirect(url_for('customer_cart'))
    
    try:
        # Verify the payment signature
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        })
    except razorpay.errors.SignatureVerificationError:
        flash('Payment verification failed. Please try again.', 'danger')
        return redirect(url_for('customer_cart'))
    
    # Payment verified — save order to DB
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cart_items = []
    subtotal = 0
    for item in cart:
        cursor.execute("""
            SELECT p.* FROM products p
            WHERE p.id = %s AND p.is_approved = 1
        """, (item['product_id'],))
        product = cursor.fetchone()
        if product:
            subtotal += float(product['price']) * item['quantity']
            cart_items.append({'product': product, 'quantity': item['quantity']})
    
    try:
        # Create order
        cursor.execute("""
            INSERT INTO orders (customer_id, order_status, total_amount, shipping_address)
            VALUES (%s, %s, %s, %s)
        """, (customer_id, 'confirmed', subtotal, shipping_address))
        new_order_id = cursor.lastrowid
        
        # Insert order items + reduce stock
        for item in cart_items:
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price_per_unit)
                VALUES (%s, %s, %s, %s)
            """, (new_order_id, item['product']['id'], item['quantity'], item['product']['price']))
            
            cursor.execute("""
                UPDATE products SET stock_quantity = stock_quantity - %s
                WHERE id = %s
            """, (item['quantity'], item['product']['id']))
        
        conn.commit()
        
        # Clear cart
        session['cart'] = []
        session.modified = True
        
        cursor.close()
        conn.close()
        
        flash(f'Payment successful! Order #{new_order_id} placed.', 'success')
                # Send order confirmation email
        try:
            cursor.execute("SELECT email FROM users WHERE id = %s", (customer_id,))
            cust = cursor.fetchone()
            if cust and cust['email']:
                email_body = f"""
                <div style="font-family:Arial,sans-serif; max-width:600px; margin:0 auto; padding:20px; background:#f4faf5;">
                    <div style="background:#fff; padding:30px; border-radius:12px;">
                        <h1 style="color:#146c43; font-family:Georgia,serif;">Order Confirmed! 🎉</h1>
                        <p>Thank you for your order <strong>#{new_order_id}</strong>.</p>
                        <p>Amount: <strong>₹{subtotal:.0f}</strong></p>
                        <p><strong>Shipping Address:</strong><br>{shipping_address}</p>
                        <p>Track your order from your dashboard.</p>
                        <a href="http://localhost:5000/customer/orders" style="display:inline-block; padding:12px 24px; background:#146c43; color:#fff; text-decoration:none; border-radius:8px; margin-top:16px;">View My Orders</a>
                        <p style="margin-top:24px; color:#888; font-size:12px;">— PartMatch Team</p>
                    </div>
                </div>
                """
                send_email(cust['email'], f'Order #{new_order_id} Confirmed — PartMatch', email_body)
        except Exception as e:
            print(f"Email error: {e}")
        return redirect(url_for('customer_orders'))
    
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        flash(f'Error saving order: {str(e)}', 'danger')
        return redirect(url_for('customer_checkout'))

# ------------------ Customer: Orders ------------------
@app.route('/customer/orders')
def customer_orders():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT o.*, 
               (SELECT COUNT(*) FROM order_items WHERE order_id = o.id) as item_count
        FROM orders o
        WHERE o.customer_id = %s
        ORDER BY o.created_at DESC
    """, (customer_id,))
    orders = cursor.fetchall()
    
    # Get items for each order
    for order in orders:
        cursor.execute("""
            SELECT oi.*, p.name as product_name, p.image, p.brand
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order['id'],))
        order['order_items'] = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/orders.html', orders=orders)

# ------------------ Customer: Download Invoice ------------------
@app.route('/customer/order/<int:order_id>/invoice')
def customer_invoice(order_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Load order (only if belongs to this customer)
    cursor.execute("""
        SELECT o.*, u.name as customer_name, u.email as customer_email, u.phone as customer_phone
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.id = %s AND o.customer_id = %s
    """, (order_id, customer_id))
    order = cursor.fetchone()
    
    if not order:
        cursor.close()
        conn.close()
        flash('Order not found.', 'danger')
        return redirect(url_for('customer_orders'))
    
    # Load order items
    cursor.execute("""
        SELECT oi.*, p.name as product_name, p.brand, p.part_number,
               u.name as vendor_name, vd.business_name
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        JOIN users u ON p.vendor_id = u.id
        LEFT JOIN vendor_details vd ON u.id = vd.user_id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('customer/invoice.html',
                         order=order,
                         items=items)

# ==================== REVIEWS & RATINGS ====================

# ------------------ Customer: Submit Product Review ------------------
@app.route('/customer/product/<int:product_id>/review', methods=['POST'])
def customer_submit_review(product_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    rating = request.form.get('rating')
    comment = request.form.get('comment', '').strip()
    
    if not rating or not (1 <= int(rating) <= 5):
        flash('Please select a valid rating.', 'danger')
        return redirect(url_for('customer_product_detail', product_id=product_id))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify the customer has purchased this product (order delivered)
    cursor.execute("""
        SELECT COUNT(*) as count FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        WHERE o.customer_id = %s AND oi.product_id = %s AND o.order_status = 'delivered'
    """, (customer_id, product_id))
    purchased = cursor.fetchone()['count']
    
    if purchased == 0:
        cursor.close()
        conn.close()
        flash('You can only review products you have purchased and received.', 'warning')
        return redirect(url_for('customer_product_detail', product_id=product_id))
    
    # Check if already reviewed
    cursor.execute("SELECT id FROM reviews WHERE user_id = %s AND product_id = %s", (customer_id, product_id))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("UPDATE reviews SET rating=%s, comment=%s WHERE id=%s", (rating, comment, existing['id']))
        flash('Your review has been updated.', 'success')
    else:
        cursor.execute("""
            INSERT INTO reviews (user_id, product_id, rating, comment)
            VALUES (%s, %s, %s, %s)
        """, (customer_id, product_id, rating, comment))
        flash('Thank you for your review!', 'success')
    
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('customer_product_detail', product_id=product_id))


# ------------------ Customer: Submit Service Center Review ------------------
@app.route('/customer/booking/<int:booking_id>/review', methods=['POST'])
def customer_submit_center_review(booking_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    rating = request.form.get('rating')
    comment = request.form.get('comment', '').strip()
    
    if not rating or not (1 <= int(rating) <= 5):
        flash('Please select a valid rating.', 'danger')
        return redirect(url_for('customer_bookings'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify the booking belongs to this customer and is completed
    cursor.execute("""
        SELECT * FROM service_bookings 
        WHERE id = %s AND customer_id = %s AND status = 'completed'
    """, (booking_id, customer_id))
    booking = cursor.fetchone()
    
    if not booking:
        cursor.close()
        conn.close()
        flash('You can only review completed services.', 'warning')
        return redirect(url_for('customer_bookings'))
    
    station_id = booking['station_id']
    
    # Check if already reviewed
    cursor.execute("SELECT id FROM reviews WHERE user_id = %s AND station_id = %s", (customer_id, station_id))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("UPDATE reviews SET rating=%s, comment=%s WHERE id=%s", (rating, comment, existing['id']))
        flash('Your review has been updated.', 'success')
    else:
        cursor.execute("""
            INSERT INTO reviews (user_id, station_id, rating, comment)
            VALUES (%s, %s, %s, %s)
        """, (customer_id, station_id, rating, comment))
        flash('Thank you for reviewing the service center!', 'success')
    
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('customer_bookings'))

# ------------------ Customer: Cancel Order ------------------
@app.route('/customer/order/<int:order_id>/cancel', methods=['POST'])
def customer_cancel_order(order_id):
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    
    customer_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify order belongs to customer and is still cancellable
    cursor.execute("""
        SELECT * FROM orders WHERE id = %s AND customer_id = %s AND order_status IN ('pending', 'confirmed')
    """, (order_id, customer_id))
    order = cursor.fetchone()
    
    if not order:
        cursor.close()
        conn.close()
        flash('Order cannot be cancelled. Only pending or confirmed orders can be cancelled.', 'warning')
        return redirect(url_for('customer_orders'))
    
    try:
        # Restore stock for each item
        cursor.execute("SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
        items = cursor.fetchall()
        
        for item in items:
            cursor.execute("""
                UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s
            """, (item['quantity'], item['product_id']))
        
        # Update order status
        cursor.execute("UPDATE orders SET order_status = 'cancelled' WHERE id = %s", (order_id,))
        conn.commit()
        
        flash(f'Order #{order_id} has been cancelled. Stock restored.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error cancelling order: {str(e)}', 'danger')
    
    cursor.close()
    conn.close()
    return redirect(url_for('customer_orders'))

# ==================== PASSWORD RESET ====================
password_reset_tokens = {}

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            token = secrets.token_urlsafe(32)
            password_reset_tokens[token] = {
                'user_id': user['id'],
                'expires': datetime.now() + timedelta(hours=1)
            }
            
            reset_link = f"http://localhost:5000/reset-password/{token}"
            body = f"""
            <div style="font-family:Arial,sans-serif; max-width:600px; margin:0 auto; padding:20px;">
                <div style="background:#fff; padding:30px; border-radius:12px; border:1px solid #d9e9dd;">
                    <h2 style="color:#146c43;">Password Reset Request</h2>
                    <p>Hi {user['name']},</p>
                    <p>Click the button below to reset your password. This link expires in 1 hour.</p>
                    <a href="{reset_link}" style="display:inline-block; padding:12px 24px; background:#146c43; color:#fff; text-decoration:none; border-radius:8px; margin-top:16px;">Reset My Password</a>
                    <p style="margin-top:20px; color:#888; font-size:13px;">If you didn't request this, ignore this email.</p>
                </div>
            </div>
            """
            send_email(email, 'Reset Your PartMatch Password', body)
            
            # Print for local testing
            print(f"\n=== PASSWORD RESET LINK for {email} ===\n{reset_link}\n")
        
        flash('If that email is registered, a reset link has been sent.', 'success')
        return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    data = password_reset_tokens.get(token)
    
    if not data or data['expires'] < datetime.now():
        flash('Reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if not new_password or len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('reset_password', token=token))
        
        if new_password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password', token=token))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        hashed = generate_password_hash(new_password)
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hashed, data['user_id']))
        conn.commit()
        cursor.close()
        conn.close()
        
        password_reset_tokens.pop(token, None)
        
        flash('Password reset successfully! Please login.', 'success')
        return redirect(url_for('home'))
    
    return render_template('reset_password.html', token=token)

# ==================== ADMIN: ALL ORDERS ====================
@app.route('/admin/orders')
def admin_orders():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    status_filter = request.args.get('status', 'all')
    search = request.args.get('q', '').strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT o.*, u.name as customer_name, u.email as customer_email, u.phone as customer_phone,
               (SELECT COUNT(*) FROM order_items WHERE order_id = o.id) as item_count
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE 1=1
    """
    params = []
    
    if status_filter != 'all':
        query += " AND o.order_status = %s"
        params.append(status_filter)
    
    if search:
        query += " AND (o.id LIKE %s OR u.name LIKE %s OR u.email LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    
    query += " ORDER BY o.created_at DESC"
    
    cursor.execute(query, params)
    orders = cursor.fetchall()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END) as delivered_count,
            SUM(CASE WHEN order_status = 'pending' THEN 1 ELSE 0 END) as pending_count
        FROM orders
    """)
    stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('admin/all_orders.html',
                         orders=orders,
                         stats=stats,
                         status_filter=status_filter,
                         search=search)

# ==================== ADMIN: REVIEWS ====================
@app.route('/admin/reviews')
def admin_reviews():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, u.name as user_name, u.email as user_email,
               p.name as product_name, sc.center_name as station_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        LEFT JOIN products p ON r.product_id = p.id
        LEFT JOIN service_center_details sc ON r.station_id = sc.user_id
        ORDER BY r.created_at DESC
    """)
    reviews = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/all_reviews.html', reviews=reviews)


@app.route('/admin/review/<int:review_id>/delete')
def admin_delete_review(review_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Review deleted.', 'info')
    return redirect(url_for('admin_reviews'))
if __name__ == '__main__':
    app.run(debug=True)
    