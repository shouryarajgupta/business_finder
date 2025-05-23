from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from main import BusinessFinder
import os
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from authlib.integrations.flask_client import OAuth
from functools import wraps
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))

# OAuth Setup
oauth = OAuth(app)
ALLOWED_EMAILS = {os.getenv('ALLOWED_EMAIL', 'shouryarajgupta@gmail.com')}

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, email):
        self.id = email

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(email):
    if email in ALLOWED_EMAILS:
        return User(email)
    return None

google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'prompt': 'select_account'
    }
)

@app.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/google-login')
def google_login():
    return google.authorize_redirect(redirect_uri=url_for('authorize', _external=True))

@app.route('/authorize')
def authorize():
    try:
        token = google.authorize_access_token()
        resp = google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info = resp.json()
        email = user_info.get('email')
        
        if email in ALLOWED_EMAILS:
            user = User(email)
            login_user(user)
            return redirect(url_for('index'))
        return "Access denied. You are not authorized to use this application.", 403
    except Exception as e:
        print(f"Authorization error: {str(e)}")
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
@login_required
def search():
    try:
        data = request.get_json()
        postal_codes = [code.strip() for code in data.get('postal_codes', '').split(',')]
        keywords = [keyword.strip() for keyword in data.get('keywords', '').split(',')]
        country = data.get('country', 'US')

        if not postal_codes or not keywords:
            return jsonify({'error': 'Missing postal codes or keywords'}), 400

        finder = BusinessFinder()
        results = finder.search_businesses(postal_codes, keywords, country)
        sheet_name = finder.export_to_sheets(results)
        
        return jsonify({
            'success': True,
            'message': f'Results exported to sheet: {sheet_name}',
            'sheet_name': sheet_name
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002))) 