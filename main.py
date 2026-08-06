#!/usr/bin/env python3
"""
JhingalaPrint.xyz Account Creator - Batch Registration
Deployed on Render with Flask Web Interface
"""

import requests
import random
import string
import time
import threading
import json
import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from collections import deque

app = Flask(__name__)

# Configuration
BASE_URL = "https://jhingalalaprint.xyz"
API_URL = f"{BASE_URL}/api.php"
REFERRAL_CODE = "RGA100010"

# Statistics
stats = {
    "total_registrations": 0,
    "successful": 0,
    "failed": 0,
    "active_threads": 0,
    "accounts_created": 0,
    "start_time": datetime.now().isoformat(),
    "status": "idle",
    "rate": 0,
    "recent_accounts": deque(maxlen=50)
}

# Account storage
accounts = []
account_lock = threading.Lock()
used_phones = set()
phone_lock = threading.Lock()

# Stop flag
stop_creation = threading.Event()
batch_size = 5
creation_thread = None

# ============= PHONE NUMBER GENERATORS =============

def generate_phone():
    """Generate random 10-digit Indian phone number"""
    with phone_lock:
        while True:
            # Start with 6,7,8,9 and 9 more digits
            first = random.choice(['6', '7', '8', '9'])
            rest = ''.join(random.choices(string.digits, k=9))
            phone = first + rest
            
            if phone not in used_phones:
                used_phones.add(phone)
                return phone

# ============= PASSWORD GENERATORS =============

def generate_password():
    """Generate strong random password"""
    length = random.randint(8, 12)
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

# ============= ACCOUNT CREATION =============

def create_single_account(index):
    """Create a single account with retry logic"""
    phone = generate_phone()
    password = generate_password()
    
    data = {
        "phone": phone,
        "password": password,
        "ref": REFERRAL_CODE,
        "action": "register"
    }
    
    try:
        resp = requests.post(
            API_URL,
            data=data,
            timeout=15,
            headers={
                "User-Agent": random.choice([
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                ]),
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/register.php"
            }
        )
        
        result = resp.json()
        
        if result.get('status') == 'success':
            account_data = {
                "phone": phone,
                "password": password,
                "referral_code": REFERRAL_CODE,
                "response": result,
                "created_at": datetime.now().isoformat()
            }
            
            with account_lock:
                accounts.append(account_data)
                stats["successful"] += 1
                stats["accounts_created"] += 1
                stats["total_registrations"] += 1
                stats["recent_accounts"].appendleft({
                    "phone": phone,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "status": "success"
                })
            
            return True, account_data
        else:
            with account_lock:
                stats["failed"] += 1
                stats["total_registrations"] += 1
                stats["recent_accounts"].appendleft({
                    "phone": phone,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "status": "failed"
                })
            return False, result.get('message', 'Unknown error')
            
    except Exception as e:
        with account_lock:
            stats["failed"] += 1
            stats["total_registrations"] += 1
            stats["recent_accounts"].appendleft({
                "phone": phone,
                "time": datetime.now().strftime("%H:%M:%S"),
                "status": "error"
            })
        return False, str(e)

def create_batch_accounts(batch_size):
    """Create multiple accounts in parallel"""
    threads = []
    results = []
    
    def worker(index):
        success, result = create_single_account(index)
        results.append((success, result))
    
    for i in range(batch_size):
        thread = threading.Thread(target=worker, args=(stats["accounts_created"] + i + 1,))
        thread.daemon = True
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()
    
    return results

def continuous_creation():
    """Continuous account creation in batches"""
    global batch_size
    
    while not stop_creation.is_set():
        with account_lock:
            stats["active_threads"] = len(threading.enumerate())
        
        # Create batch of accounts
        batch_results = create_batch_accounts(batch_size)
        
        # Small delay between batches (1 second)
        time.sleep(1)

# ============= FLASK WEB INTERFACE =============

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>JhingalaPrint Account Creator</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #121e1a; color: #e6fc51; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .container { max-width: 900px; margin: 30px auto; padding: 20px; background: #0f1c18; border: 1px solid #e6fc51; border-radius: 10px; }
        .stat-box { background: #1a3029; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 3px solid #e6fc51; }
        .stat-value { font-size: 2em; font-weight: bold; color: #e6fc51; }
        .stat-label { color: #8b949e; font-size: 0.9em; text-transform: uppercase; }
        .success { color: #56d364; }
        .failed { color: #f85149; }
        .status-running { color: #56d364; animation: blink 1s infinite; }
        .status-idle { color: #e3b341; }
        @keyframes blink { 50% { opacity: 0; } }
        .account-list { max-height: 400px; overflow-y: auto; font-size: 0.8em; }
        .account-list::-webkit-scrollbar { width: 5px; }
        .account-list::-webkit-scrollbar-track { background: #1a3029; }
        .account-list::-webkit-scrollbar-thumb { background: #e6fc51; border-radius: 5px; }
        .btn-control { background: #e6fc51; color: #0f1c18; border: none; padding: 10px 20px; font-weight: bold; }
        .btn-control:hover { background: #c4e63c; color: #0f1c18; }
        .btn-control:disabled { background: #444; color: #888; cursor: not-allowed; }
        h1 { border-bottom: 1px solid #1a3029; padding-bottom: 10px; }
        .refresh-btn { background: #1a3029; color: #e6fc51; border: 1px solid #e6fc51; padding: 5px 15px; float: right; }
        .refresh-btn:hover { background: #243b34; }
        .phone-preview { color: #58a6ff; font-size: 0.85em; }
        .badge-refer { background: #e3b341; color: #0f1c18; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
        .badge-api { background: #58a6ff; color: #0f1c18; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
        .batch-btn { background: #1a3029; color: #e6fc51; border: 1px solid #e6fc51; padding: 5px 15px; margin: 2px; }
        .batch-btn:hover { background: #243b34; }
        .batch-btn.active { background: #e6fc51; color: #0f1c18; }
        .custom-input { background: #1a3029; color: #e6fc51; border: 1px solid #e6fc51; padding: 5px 10px; width: 80px; }
        .custom-input:focus { outline: none; border-color: #c4e63c; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ JhingalaPrint Account Creator
            <span class="badge-api">API</span>
            <span class="badge-refer">REF: RGA100003</span>
            <button class="refresh-btn" onclick="location.reload()">⟳ Refresh</button>
        </h1>
        
        <div class="row mt-3">
            <div class="col-md-6">
                <button class="btn-control w-100" id="controlBtn" onclick="toggleCreation()">
                    {{ '⏹ Stop' if stats.status == 'running' else '▶ Start' }}
                </button>
            </div>
            <div class="col-md-6">
                <button class="btn-control w-100" style="background:#f85149;color:#fff;" onclick="clearAccounts()">
                    🗑 Clear All
                </button>
            </div>
        </div>
        
        <div class="row mt-3">
            <div class="col-12">
                <label class="stat-label">Batch Size:</label>
                <button class="batch-btn" onclick="setBatch(5)" id="batch5">5</button>
                <button class="batch-btn" onclick="setBatch(10)" id="batch10">10</button>
                <button class="batch-btn" onclick="setBatch(50)" id="batch50">50</button>
                <button class="batch-btn" onclick="setBatch(100)" id="batch100">100</button>
                <button class="batch-btn" onclick="setCustomBatch()" id="batchCustom">Custom</button>
                <input type="number" class="custom-input" id="customBatch" placeholder="Count" min="1" max="1000">
                <span id="currentBatch" class="stat-label" style="margin-left:10px;">Current: {{ batch_size }}</span>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">Total Registrations</div>
                    <div class="stat-value">{{ stats.total_registrations }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">Successful</div>
                    <div class="stat-value success">{{ stats.successful }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value failed">{{ stats.failed }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">Status</div>
                    <div class="stat-value {{ 'status-running' if stats.status == 'running' else 'status-idle' }}">
                        {{ stats.status.upper() }}
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row mt-3">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Active Threads</div>
                    <div class="stat-value">{{ stats.active_threads }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Accounts Created</div>
                    <div class="stat-value">{{ stats.accounts_created }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Start Time</div>
                    <div style="font-size:0.9em;color:#8b949e;">{{ stats.start_time }}</div>
                </div>
            </div>
        </div>
        
        <div class="mt-4">
            <h4>Recent Registrations (last 50) 
                <span class="badge-api">@phone</span>
                <span style="color:#56d364;font-size:0.8em;">✅ Success</span>
                <span style="color:#f85149;font-size:0.8em;">❌ Failed</span>
            </h4>
            <div class="account-list">
                <table class="table table-dark table-sm">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Phone</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for acc in stats.recent_accounts %}
                        <tr>
                            <td>{{ acc.time }}</td>
                            <td class="phone-preview">{{ acc.phone }}</td>
                            <td class="{{ 'success' if acc.status == 'success' else 'failed' }}">
                                {{ '✅' if acc.status == 'success' else '❌' }}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="mt-4">
            <a href="/download" class="btn btn-success btn-sm">⬇ Download Accounts ({{ stats.accounts_created }})</a>
            <a href="/stats" class="btn btn-info btn-sm">📊 JSON Stats</a>
            <span style="float:right;color:#8b949e;font-size:0.8em;">1 request per second</span>
        </div>
    </div>
    
    <script>
        let currentBatch = {{ batch_size }};
        
        function toggleCreation() {
            fetch('/toggle', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'running') {
                        document.getElementById('controlBtn').textContent = '⏹ Stop';
                        document.getElementById('controlBtn').style.background = '#f85149';
                        document.getElementById('controlBtn').style.color = '#fff';
                    } else {
                        document.getElementById('controlBtn').textContent = '▶ Start';
                        document.getElementById('controlBtn').style.background = '#e6fc51';
                        document.getElementById('controlBtn').style.color = '#0f1c18';
                    }
                    setTimeout(() => location.reload(), 1000);
                });
        }
        
        function clearAccounts() {
            if (confirm('Delete all accounts? This cannot be undone!')) {
                fetch('/clear', { method: 'POST' })
                    .then(() => location.reload());
            }
        }
        
        function setBatch(size) {
            currentBatch = size;
            document.getElementById('currentBatch').textContent = 'Current: ' + size;
            
            // Highlight active button
            document.querySelectorAll('.batch-btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById('batch' + size).classList.add('active');
            
            fetch('/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_size: size })
            });
        }
        
        function setCustomBatch() {
            const input = document.getElementById('customBatch');
            const size = parseInt(input.value);
            if (size && size > 0) {
                setBatch(size);
            } else {
                alert('Please enter a valid number');
            }
        }
        
        // Auto refresh every 5 seconds
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main dashboard"""
    with account_lock:
        stats_copy = {
            "total_registrations": stats["total_registrations"],
            "successful": stats["successful"],
            "failed": stats["failed"],
            "active_threads": stats["active_threads"],
            "accounts_created": stats["accounts_created"],
            "start_time": stats["start_time"],
            "status": stats["status"],
            "rate": stats["rate"],
            "recent_accounts": list(stats["recent_accounts"])
        }
    return render_template_string(HTML_TEMPLATE, stats=stats_copy, batch_size=batch_size)

@app.route('/stats')
def get_stats():
    """Get JSON statistics"""
    with account_lock:
        stats_copy = {
            "total_registrations": stats["total_registrations"],
            "successful": stats["successful"],
            "failed": stats["failed"],
            "accounts_created": stats["accounts_created"],
            "active_threads": stats["active_threads"],
            "status": stats["status"],
            "rate": stats["rate"],
            "start_time": stats["start_time"],
            "uptime_seconds": (datetime.now() - datetime.fromisoformat(stats["start_time"])).total_seconds()
        }
    return jsonify(stats_copy)

@app.route('/download')
def download_accounts():
    """Download all accounts as CSV"""
    with account_lock:
        if not accounts:
            return "No accounts found", 404
        
        csv_data = "Phone,Password,ReferralCode,CreatedAt\n"
        for acc in accounts:
            csv_data += f"{acc['phone']},{acc['password']},{acc['referral_code']},{acc['created_at']}\n"
    
    return csv_data, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    }

@app.route('/toggle', methods=['POST'])
def toggle_creation():
    """Start/Stop account creation"""
    global creation_thread, batch_size
    
    if stats["status"] == "running":
        stop_creation.set()
        stats["status"] = "stopping"
        return jsonify({"status": "stopping"})
    else:
        stop_creation.clear()
        stats["status"] = "running"
        stats["start_time"] = datetime.now().isoformat()
        creation_thread = threading.Thread(target=continuous_creation, daemon=True)
        creation_thread.start()
        return jsonify({"status": "running"})

@app.route('/batch', methods=['POST'])
def set_batch():
    """Set batch size"""
    global batch_size
    data = request.get_json()
    if data and 'batch_size' in data:
        batch_size = int(data['batch_size'])
        if batch_size < 1:
            batch_size = 1
        if batch_size > 1000:
            batch_size = 1000
    return jsonify({"batch_size": batch_size})

@app.route('/clear', methods=['POST'])
def clear_accounts():
    """Clear all accounts"""
    with account_lock:
        accounts.clear()
        stats["total_registrations"] = 0
        stats["successful"] = 0
        stats["failed"] = 0
        stats["accounts_created"] = 0
        stats["recent_accounts"].clear()
        used_phones.clear()
    return jsonify({"status": "cleared"})

@app.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint for Uptime Robot"""
    return jsonify({
        "status": "alive",
        "accounts": stats["accounts_created"],
        "time": datetime.now().isoformat()
    })

# ============= MAIN =============

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Start account creation automatically
    stop_creation.clear()
    stats["status"] = "running"
    stats["start_time"] = datetime.now().isoformat()
    
    creation_thread = threading.Thread(target=continuous_creation, daemon=True)
    creation_thread.start()
    
    # Run Flask app
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
