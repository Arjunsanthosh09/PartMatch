from flask import Blueprint, render_template, request, redirect, url_for

customer_bp = Blueprint('customer', __name__, url_prefix='/customer')

@customer_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        
        return redirect(url_for('customer.dashboard'))
    return render_template('customer/register.html')