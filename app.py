from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from main import BusinessFinder
import os
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from authlib.integrations.flask_client import OAuth
from functools import wraps
import traceback

# Debug logging for environment variables
print("----- ENV DEBUG -----")
print("SECRET_KEY:", repr(os.getenv('SECRET_KEY')))
print("ALLOWED_EMAILS raw value:", repr(os.getenv('ALLOWED_EMAILS')))
print("All environment variables:", {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')})  # Filter out Python-specific vars for clarity
print("---------------------")

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

# Initialize Flask app
app = Flask(__name__)

# Only load dotenv in development
if os.getenv('RENDER') is None:  # We're in development
    from dotenv import load_dotenv
    load_dotenv()

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

# Debug: Print all environment variables (excluding sensitive ones)
print("Available environment variables:", [k for k in os.environ.keys() if not any(x in k.lower() for x in ['key', 'secret', 'token', 'password'])])

def process_allowed_emails(email_string: str) -> set:
    """Process comma-separated email string into a set of valid emails."""
    emails = set()
    if not email_string:
        return emails
        
    print(f"Processing email string: {repr(email_string)}")
    # Split by comma and handle optional spaces
    for email in email_string.split(','):
        cleaned_email = email.strip().lower()
        if cleaned_email and '@' in cleaned_email:  # Basic email validation
            emails.add(cleaned_email)
            print(f"✓ Added authorized email: {cleaned_email}")
        else:
            print(f"! Skipped invalid email: {repr(email)}")
    return emails

def process_allowed_domains(domain_string: str) -> set:
    """Process comma-separated domain string into a set of valid domains."""
    domains = set()
    if not domain_string:
        return domains
        
    print(f"Processing domain string: {repr(domain_string)}")
    # Split by comma and handle optional spaces
    for domain in domain_string.split(','):
        cleaned_domain = domain.strip().lower()
        if cleaned_domain:  # Basic domain validation
            domains.add(cleaned_domain)
            print(f"✓ Added authorized domain: {cleaned_domain}")
        else:
            print(f"! Skipped invalid domain: {repr(domain)}")
    return domains

# Get configuration from environment
raw_emails = os.getenv('ALLOWED_EMAILS', '')
raw_domains = os.getenv('ALLOWED_DOMAINS', '')

print(f"Raw ALLOWED_EMAILS value: {repr(raw_emails)}")
print(f"Raw ALLOWED_DOMAINS value: {repr(raw_domains)}")

# Process the emails and domains
ALLOWED_EMAILS = process_allowed_emails(raw_emails)
ALLOWED_DOMAINS = process_allowed_domains(raw_domains)

print(f"Final authorized emails ({len(ALLOWED_EMAILS)}):", sorted(list(ALLOWED_EMAILS)))
print(f"Final authorized domains ({len(ALLOWED_DOMAINS)}):", sorted(list(ALLOWED_DOMAINS)))
log_auth("Authorization configured", emails=sorted(list(ALLOWED_EMAILS)), domains=sorted(list(ALLOWED_DOMAINS)))

# Also check if we're running on Render
if os.getenv('RENDER') is not None:
    print("Running on Render environment")
    print("Render service name:", os.getenv('RENDER_SERVICE_NAME'))
    print("Render external URL:", os.getenv('RENDER_EXTERNAL_URL'))

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, email):
        self.id = email.strip()  # Ensure email is stripped of whitespace

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(email):
    email = email.strip()  # Ensure email is stripped of whitespace
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
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
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
        
        # Use the correct OpenID Connect userinfo endpoint
        resp = google.get('https://openidconnect.googleapis.com/v1/userinfo')
        user_info = resp.json()
        email = user_info.get('email', '').strip().lower()  # Ensure email is lowercase
        
        if not email:
            log_auth("No email in user info", error=True, user_info=user_info)
            return "Email not provided by Google. Please ensure you have granted email permission.", 400
            
        log_auth("User info retrieved", email=email)
        print(f"Checking authorization for: {email}")
        
        # Check if any authorization rules are configured
        if not ALLOWED_EMAILS and not ALLOWED_DOMAINS:
            log_auth("No authorization rules configured", error=True)
            return ("No authorization rules configured. Please set ALLOWED_EMAILS or ALLOWED_DOMAINS "
                   "in the environment variables."), 403
        
        # Check both specific email and domain
        email_domain = email.split('@')[-1].lower()
        is_allowed = email in ALLOWED_EMAILS or email_domain in ALLOWED_DOMAINS
        
        print(f"Email check: {email in ALLOWED_EMAILS}")
        print(f"Domain check ({email_domain}): {email_domain in ALLOWED_DOMAINS}")
        print(f"Final authorization result: {is_allowed}")
        
        if is_allowed:
            user = User(email)
            login_user(user)
            log_auth("User successfully authenticated", 
                    email=email, 
                    auth_type="specific_email" if email in ALLOWED_EMAILS else "domain")
            return redirect(url_for('home'))
            
        log_auth("Unauthorized email attempt", error=True, 
                email=email,
                domain=email_domain,
                allowed_emails=sorted(list(ALLOWED_EMAILS)),
                allowed_domains=sorted(list(ALLOWED_DOMAINS)))
        
        # Provide specific feedback about why access was denied
        if ALLOWED_EMAILS and ALLOWED_DOMAINS:
            message = (f"Access denied. Your email ({email}) is not in the allowed list "
                      f"and your domain ({email_domain}) is not authorized.")
        elif ALLOWED_EMAILS:
            message = f"Access denied. Your email ({email}) is not in the allowed list."
        else:  # ALLOWED_DOMAINS must be set due to earlier check
            message = f"Access denied. Your domain ({email_domain}) is not authorized."
            
        return message + " Please contact the administrator.", 403
        
    except Exception as e:
        error_details = traceback.format_exc()
        log_auth("Authorization failed", error=True, 
                error_message=str(e), 
                error_details=error_details)
        return "Authentication failed. Please try again or contact the administrator.", 400

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
        max_results = data.get('max_results')
        if max_results:
            try:
                max_results = int(max_results)
            except ValueError:
                max_results = None
        
        print(f"Processed inputs - Postal codes: {postal_codes}, Keywords: {keywords}, Country: {country}, Max Results: {max_results}")

        if not postal_codes or not keywords:
            return jsonify({'error': 'Missing postal codes or keywords'}), 400

        # Validate input size
        if len(postal_codes) > 5:
            return jsonify({'error': 'Maximum 5 postal codes allowed per request'}), 400
        if len(keywords) > 5:
            return jsonify({'error': 'Maximum 5 keywords allowed per request'}), 400

        print("Initializing BusinessFinder...")
        finder = BusinessFinder()
        
        print("Starting business search...")
        try:
            results = finder.search_businesses(postal_codes, keywords, country, max_results)
            print(f"Search completed. Found {len(results)} results")
            
            if not results:
                return jsonify({
                    'success': True,
                    'message': 'No businesses found matching your criteria.',
                    'results': []
                })
            
            print("Exporting to sheets...")
            sheet_name = finder.export_to_sheets(results)
            print(f"Export completed to sheet: {sheet_name}")
            
            return jsonify({
                'success': True,
                'message': f'Results exported to sheet: {sheet_name}',
                'sheet_name': sheet_name,
                'spreadsheet_id': os.getenv('SPREADSHEET_ID'),
                'result_count': len(results)
            })
            
        except TimeoutError:
            return jsonify({
                'error': 'The search operation timed out. Please try with fewer postal codes or keywords.'
            }), 408
            
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"Search error: {str(e)}")
        print(f"Error traceback: {error_details}")
        
        # Return a more user-friendly error message
        error_message = str(e)
        if "quota" in error_message.lower():
            error_message = "API quota exceeded. Please try again later."
        elif "timeout" in error_message.lower():
            error_message = "The request timed out. Please try with fewer postal codes or keywords."
        
        return jsonify({
            'error': error_message,
            'details': error_details if os.getenv('FLASK_ENV') == 'development' else None
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