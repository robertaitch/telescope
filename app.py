from flask import session
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, jsonify
from checker_wrapper import TelegramCheckerWrapper
import atexit
import os
import json
from pathlib import Path

app = Flask(__name__)
app.secret_key = 'telescope-secret-key-change-in-production'
checker = TelegramCheckerWrapper()

CREDENTIALS_FILE = Path("saved_credentials.json")

def cleanup_checker():
    if checker:
        checker.cleanup()

def save_credentials(api_id, api_hash, phone):
    credentials = {
        'api_id': api_id,
        'api_hash': api_hash,
        'phone': phone
    }
    try:
        with open(CREDENTIALS_FILE, 'w') as f:
            json.dump(credentials, f)
        return True
    except Exception as e:
        print(f"Error saving credentials: {e}")
        return False

def load_saved_credentials():
    try:
        if CREDENTIALS_FILE.exists():
            with open(CREDENTIALS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading credentials: {e}")
    return None

def clear_saved_credentials():
    try:
        if CREDENTIALS_FILE.exists():
            os.remove(CREDENTIALS_FILE)
    except Exception as e:
        print(f"Error clearing credentials: {e}")

atexit.register(cleanup_checker)

@app.route('/', methods=['GET', 'POST'])
def index():
    saved_creds = load_saved_credentials()
    
    if request.method == 'POST':
        api_id = request.form['api_id']
        api_hash = request.form['api_hash']
        phone = request.form['phone']
        save_session = request.form.get('save_session', False)
        
        session['api_id'] = api_id
        session['api_hash'] = api_hash
        session['phone'] = phone
        
        if save_session:
            if save_credentials(api_id, api_hash, phone):
                flash('Credentials saved successfully!', 'success')
            else:
                flash('Failed to save credentials', 'error')
        
        checker.set_config(api_id, api_hash, phone)
        if checker.run_initialize():
            flash('Successfully connected to Telegram!', 'success')
            return redirect(url_for('search'))
        return redirect(url_for('verify'))
    
    return render_template('index.html', saved_credentials=saved_creds)

@app.route('/load_saved', methods=['POST'])
def load_saved():
    saved_creds = load_saved_credentials()
    if saved_creds:
        session['api_id'] = saved_creds['api_id']
        session['api_hash'] = saved_creds['api_hash']
        session['phone'] = saved_creds['phone']
        
        checker.set_config(saved_creds['api_id'], saved_creds['api_hash'], saved_creds['phone'])
        if checker.run_initialize():
            flash('Successfully loaded saved credentials!', 'success')
            return redirect(url_for('search'))
        return redirect(url_for('verify'))
    
    flash('No saved credentials found', 'error')
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search():
    if not session.get('api_id'):
        flash('Please authenticate first', 'error')
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        input_type = request.form['input_type']
        value = request.form['value']
        
        flash(f'Searching for {input_type}: {value}...', 'info')
        
        if input_type == 'phone':
            result = checker.run_phone_check(value)
        else:
            result = checker.run_username_check(value)
            
        if result:
            flash('User found successfully!', 'success')
        else:
            flash('User not found or search failed', 'error')
            
        return render_template('result.html', result=result, search_query=value, search_type=input_type)
    
    return render_template('search.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if not session.get('api_id'):
        flash('Please authenticate first', 'error')
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        code = request.form['code']
        try:
            checker.submit_code(code)
            flash('Verification successful!', 'success')
            return redirect(url_for('search'))
        except Exception as e:
            flash(f'Verification failed: {str(e)}', 'error')
            return render_template('verify.html')
    return render_template('verify.html')

@app.route('/profile_photos/<filename>')
def serve_photo(filename):
    try:
        return send_from_directory('profile_photos', filename)
    except Exception as e:
        print(f"Error serving photo {filename}: {e}")
        return '', 404

@app.route('/reset')
def reset():
    session.clear()
    global checker
    checker.cleanup()
    checker = TelegramCheckerWrapper()
    flash('Session reset successfully', 'info')
    return redirect(url_for('index'))

@app.route('/clear_saved')
def clear_saved():
    clear_saved_credentials()
    flash('Saved credentials cleared', 'info')
    return redirect(url_for('index'))

@app.route('/api/search_status')
def search_status():
    return jsonify({
        'authenticated': bool(session.get('api_id')),
        'needs_verification': checker.needs_verification() if session.get('api_id') else False
    })

if __name__ == "__main__":
    os.makedirs('profile_photos', exist_ok=True)
    os.makedirs('results', exist_ok=True)
    app.run(debug=True, use_reloader=False, threaded=True)