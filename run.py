from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__,
            template_folder="app/templates",
            static_folder="app/static")
app.secret_key = 'your-secret-key-change-me'

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
@app.route('/')
def home():
    return render_template('base.html')

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
@app.route('/customer/dashboard')
def customer_dashboard():
    if 'user_id' not in session or session.get('role') != 'customer':
        flash('Please login as a customer.', 'warning')
        return redirect(url_for('home'))
    return render_template('customer/dashboard.html')

# ------------------ Vendor Dashboard ------------------
@app.route('/vendor/dashboard')
def vendor_dashboard():
    if 'user_id' not in session or session.get('role') != 'vendor':
        flash('Please login as a vendor.', 'warning')
        return redirect(url_for('home'))
    return render_template('vendor/dashboard.html')

# ------------------ Service Center Dashboard ------------------
@app.route('/service_center/dashboard')
def service_center_dashboard():
    if 'user_id' not in session or session.get('role') != 'service_center':
        flash('Please login as a service center.', 'warning')
        return redirect(url_for('home'))
    return render_template('service_center/dashboard.html')   # You'll need to create this template

# ------------------ Admin Dashboard ------------------
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Please login as an admin.', 'warning')
        return redirect(url_for('home'))
    return render_template('admin/dashboard.html')

if __name__ == '__main__':
    app.run(debug=True)