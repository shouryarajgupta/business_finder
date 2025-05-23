from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from main import BusinessFinder
import os
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from authlib.integrations.flask_client import OAuth
from functools import wraps
from dotenv import load_dotenv
import traceback

def log_auth(step: str, error: bool = False, **kwargs):
    """Helper function to log authentication steps."""
    line = "=" * 50
    status = "ERROR" if error else "INFO"
    print(f"\n{line}")
    print(f"AUTH {status}: {step}")
    for key, value in kwargs.items():
        # Safely mask sensitive values
        if key in ['token', 'client_secret', 'access_token']:
            print(f"{key}: {'*' * 10}")
        else:
            print(f"{key}: {value}")
    print(f"{line}\n")

# Load environment variables
load_dotenv()

app = Flask(__name__)
try:
    app.secret_key = os.getenv('SECRET_KEY')
    if not app.secret_key:
        raise ValueError("No SECRET_KEY set in environment variables")
    log_auth("Secret key loaded successfully")
except Exception as e:
    log_auth("Failed to load secret key", error=True, error_details=str(e))
    raise

# OAuth Setup
oauth = OAuth(app)
ALLOWED_EMAILS = {os.getenv('ALLOWED_EMAIL', 'shouryarajgupta@gmail.com')}
log_auth("Allowed emails configured", emails=list(ALLOWED_EMAILS))

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

# OAuth 2.0 client setup
try:
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    
    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID not found in environment variables")
    if not GOOGLE_CLIENT_SECRET:
        raise ValueError("GOOGLE_CLIENT_SECRET not found in environment variables")
    
    log_auth("Google OAuth credentials loaded", client_id=GOOGLE_CLIENT_ID[:10] + '...')
    
    google = oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        access_token_url='https://accounts.google.com/o/oauth2/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        api_base_url='https://www.googleapis.com/oauth2/v3/',
        client_kwargs={'scope': 'openid email profile'}
    )
    log_auth("Google OAuth client registered successfully")
    
except Exception as e:
    log_auth("Failed to setup Google OAuth", error=True, error_details=str(e))
    raise

@app.route('/')
def home():
    if current_user.is_authenticated:
        log_auth("User already authenticated, showing home page", user=current_user.id)
        return render_template('index.html')
    log_auth("User not authenticated, showing login page")
    return render_template('login.html')

@app.route('/login')
def login():
    if current_user.is_authenticated:
        log_auth("User already authenticated, redirecting to home", user=current_user.id)
        return redirect(url_for('home'))
    log_auth("Showing login page")
    return render_template('login.html')

@app.route('/google-login')
def google_login():
    try:
        redirect_uri = url_for('authorize', _external=True)
        log_auth("Starting Google OAuth flow", redirect_uri=redirect_uri)
        return google.authorize_redirect(redirect_uri)
    except Exception as e:
        log_auth("Failed to start OAuth flow", error=True, error_details=str(e))
        return redirect(url_for('login'))

@app.route('/authorize')
def authorize():
    try:
        log_auth("Processing OAuth callback")
        token = google.authorize_access_token()
        log_auth("Access token obtained")
        
        resp = google.get('userinfo')
        user_info = resp.json()
        email = user_info.get('email')
        
        if not email:
            log_auth("No email in user info", error=True, user_info=user_info)
            return "Email not provided by Google.", 400
            
        log_auth("User info retrieved", email=email)
        
        if email in ALLOWED_EMAILS:
            user = User(email)
            login_user(user)
            log_auth("User successfully authenticated", email=email)
            return redirect(url_for('home'))
            
        log_auth("Unauthorized email attempt", error=True, email=email)
        return "Access denied. You are not authorized to use this application.", 403
        
    except Exception as e:
        error_details = traceback.format_exc()
        log_auth("Authorization failed", error=True, 
                error_message=str(e), 
                error_details=error_details)
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    email = current_user.id
    logout_user()
    log_auth("User logged out", email=email)
    return redirect(url_for('login'))

@app.route('/search', methods=['POST'])
@login_required
def search():
    try:
        print("Starting search request...")
        data = request.get_json()
        if not data:
            data = request.form.to_dict()
        print(f"Received data: {data}")
        
        postal_codes = [code.strip() for code in data.get('postal_codes', '').split(',')]
        keywords = [keyword.strip() for keyword in data.get('keywords', '').split(',')]
        country = data.get('country', 'US')
        print(f"Processed inputs - Postal codes: {postal_codes}, Keywords: {keywords}, Country: {country}")

        if not postal_codes or not keywords:
            return jsonify({'error': 'Missing postal codes or keywords'}), 400

        print("Initializing BusinessFinder...")
        finder = BusinessFinder()
        
        print("Starting business search...")
        results = finder.search_businesses(postal_codes, keywords, country)
        print(f"Search completed. Found {len(results)} results")
        
        print("Exporting to sheets...")
        sheet_name = finder.export_to_sheets(results)
        print(f"Export completed to sheet: {sheet_name}")
        
        return jsonify({
            'success': True,
            'message': f'Results exported to sheet: {sheet_name}',
            'sheet_name': sheet_name
        })
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"Search error: {str(e)}")
        print(f"Error traceback: {error_details}")
        return jsonify({
            'error': str(e),
            'details': error_details
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('login.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002))) 