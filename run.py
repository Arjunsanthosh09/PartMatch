from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json

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
    elif action == 'reject':
        cursor.execute("DELETE FROM vendor_details WHERE user_id = %s", (vendor_id,))
        cursor.execute("DELETE FROM users WHERE id = %s AND role = 'vendor'", (vendor_id,))
        flash('Vendor rejected and removed.', 'danger')
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_vendors'))

# ==================== MANAGE SERVICE CENTERS ====================
@app.route('/admin/service-centers')
def admin_service_centers():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.phone, u.created_at,
               sc.center_name, sc.city, sc.is_approved
        FROM users u
        JOIN service_center_details sc ON u.id = sc.user_id
        WHERE u.role = 'service_center'
        ORDER BY u.created_at DESC
    """)
    centers = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin/manage_service_centers.html', centers=centers)

# ==================== APPROVE/REJECT SERVICE CENTER ====================
@app.route('/admin/service-center/<int:center_id>/<action>')
def admin_center_action(center_id, action):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if action == 'approve':
        cursor.execute("UPDATE service_center_details SET is_approved = 1 WHERE user_id = %s", (center_id,))
        cursor.execute("UPDATE users SET is_verified = 1 WHERE id = %s AND role = 'service_center'", (center_id,))
        flash('Service center approved successfully!', 'success')
    elif action == 'reject':
        cursor.execute("DELETE FROM service_center_details WHERE user_id = %s", (center_id,))
        cursor.execute("DELETE FROM users WHERE id = %s AND role = 'service_center'", (center_id,))
        flash('Service center rejected and removed.', 'danger')
    
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
    
if __name__ == '__main__':
    app.run(debug=True)