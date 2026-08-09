# arena.py
#!/usr/bin/env python3
"""
ARENA Unlimited Account Creator - High Speed with Proxy Rotation
Combined Proxy Logic + Account Creation
Deployed on Render with Flask Web Interface
"""

import os
import time
import random
import json
import threading
import requests
import string
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template_string, Response
from collections import deque

app = Flask(__name__)

# ============= CONFIGURATION =============
BASE_URL = "https://s2-api.digicroz.com"
MAX_WORKERS = 50  # Number of concurrent registration threads
PROXY_BATCH_SIZE = 200  # Proxies to fetch at a time
MIN_PROXY_QUEUE = 30  # Minimum proxies before refill
REGISTRATION_TIMEOUT = 10

# ============= GLOBAL STATE =============
STATE = {
    "start_time": time.time(),
    "start_time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "total_attempts": 0,
    "successful": 0,
    "failed": 0,
    "active_threads": 0,
    "rate": 0,
    "status": "idle",
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "recent_accounts": deque(maxlen=50),
    "logs": []
}

# Queues and Locks
PROXIES_LIVE_QUEUE = []
ACCOUNTS = []
ACCOUNT_LOCK = threading.Lock()
PROXY_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
STOP_CREATION = threading.Event()

# Request tracking for rate limiting
REQUEST_TIMES = deque(maxlen=100)

# ============= LOGGING SYSTEM =============
def log_sys(msg, level="info", target="N/A", proxy="N/A"):
    """Thread-safe logging system"""
    with LOG_LOCK:
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": msg,
            "level": level,
            "target": target,
            "proxy": proxy
        }
        STATE["logs"].insert(0, entry)
        if len(STATE["logs"]) > 2000:
            STATE["logs"] = STATE["logs"][:2000]

# ============= NAME GENERATORS =============
FIRST_NAMES = [
    "Raj", "Amit", "Priya", "Suresh", "Neha", "Vikram", "Anjali", "Rahul", "Pooja", "Arun",
    "Kiran", "Meena", "Sunil", "Deepa", "Manoj", "Sita", "Ravi", "Geeta", "Naveen", "Kavya",
    "Aisha", "Kabir", "Zara", "Arjun", "Mira", "Karan", "Riya", "Dev", "Sara", "Aditya",
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth",
    "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
    "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Kumar", "Singh", "Reddy", "Rao", "Joshi", "Gupta", "Mehta",
    "Choudhary", "Desai", "Nair", "Menon", "Iyer", "Pillai", "Acharya", "Bhatt", "Das", "Mishra",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee"
]

def generate_name():
    """Generate random name"""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    if random.random() < 0.2:
        first, last = last, first
    return first, last

def generate_username():
    """Generate clean username"""
    patterns = [
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(100, 9999)}",
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))}{random.randint(100, 9999)}",
        lambda: f"user{random.randint(10000, 999999)}",
        lambda: f"play{random.randint(10000, 999999)}",
        lambda: f"game{random.randint(10000, 999999)}",
        lambda: f"win{random.randint(10000, 999999)}",
        lambda: f"{random.choice(['gamer', 'player', 'winner', 'champion', 'master', 'pro', 'elite', 'legend', 'hero'])}{random.randint(100, 9999)}",
    ]
    return random.choice(patterns)()

def generate_phone():
    """Generate Indian phone number"""
    return random.choice(['6','7','8','9']) + ''.join(random.choices(string.digits, k=9))

def generate_email():
    """Generate random email"""
    return f"{generate_username()}@{random.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com'])}"

def generate_password():
    """Generate strong password"""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    length = random.randint(12, 18)
    return ''.join(random.choices(chars, k=length))

# ============= PROXY MANAGEMENT =============
def fetch_raw_proxies():
    """Fetches free proxies from multiple sources"""
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
    ]
    
    raw_proxies = set()
    log_sys("SYSTEM: Fetching fresh proxies...", "info")
    
    for url in sources:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    proxy = line.strip()
                    if ":" in proxy:
                        raw_proxies.add(proxy)
        except Exception as e:
            log_sys(f"SYSTEM: Failed to fetch from {url}", "warn")
    
    proxy_list = list(raw_proxies)
    random.shuffle(proxy_list)
    return proxy_list[:500]

def check_single_proxy(proxy):
    """Checks if a proxy is alive"""
    proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    try:
        res = requests.get("http://connectivitycheck.gstatic.com/generate_204", proxies=proxy_dict, timeout=5)
        if res.status_code == 204:
            with PROXY_LOCK:
                PROXIES_LIVE_QUEUE.append(proxy)
                STATE["proxies_live"] += 1
            return True
    except:
        pass
    with PROXY_LOCK:
        STATE["proxies_dead"] += 1
    return False

def proxy_manager_thread():
    """Background thread to maintain proxy queue"""
    while True:
        with PROXY_LOCK:
            queue_size = len(PROXIES_LIVE_QUEUE)
        
        if queue_size < MIN_PROXY_QUEUE:
            log_sys(f"SYSTEM: Proxy queue low ({queue_size}). Refilling...", "info")
            new_proxies = fetch_raw_proxies()
            with PROXY_LOCK:
                STATE["proxies_fetched"] += len(new_proxies)
            
            log_sys(f"SYSTEM: Testing {len(new_proxies)} proxies...", "info")
            
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = [executor.submit(check_single_proxy, p) for p in new_proxies]
                for f in as_completed(futures):
                    pass
            
            with PROXY_LOCK:
                log_sys(f"SYSTEM: Proxy queue now {len(PROXIES_LIVE_QUEUE)}", "success")
        
        time.sleep(3)

def get_proxy():
    """Get a live proxy from the queue"""
    with PROXY_LOCK:
        if PROXIES_LIVE_QUEUE:
            proxy = PROXIES_LIVE_QUEUE.pop(0)
            STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
            return proxy
    return None

def return_proxy(proxy):
    """Return a proxy to the queue (reuse if still good)"""
    if proxy:
        with PROXY_LOCK:
            PROXIES_LIVE_QUEUE.append(proxy)
            STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)

# ============= ACCOUNT CREATION =============
def register_single_account(worker_id):
    """Register a single account using a proxy"""
    # Get a proxy
    proxy = get_proxy()
    if not proxy:
        return False, "No proxy available"
    
    proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    
    # Generate user data
    first_name, last_name = generate_name()
    username = generate_username()
    phone = generate_phone()
    email = generate_email()
    password = generate_password()
    
    # Build tRPC request
    url = "https://s2-api.digicroz.com/trpc/rebelXArena/webApp/rebelXArena/auth.register?batch=1"
    
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://web-app.rebelxarena.com",
        "referer": "https://web-app.rebelxarena.com/",
        "user-agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.{worker_id} Safari/537.36"
    }
    
    payload = {
        "0": {
            "json": {
                "firstName": first_name,
                "lastName": last_name,
                "username": username,
                "countryCode": "+91",
                "mobileNumber": phone,
                "email": email,
                "password": password
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, proxies=proxy_dict, timeout=REGISTRATION_TIMEOUT)
        
        with ACCOUNT_LOCK:
            STATE["total_attempts"] += 1
        
        if response.status_code == 200:
            try:
                result = response.json()
                # Check for success (tRPC response format)
                if "0" in result and "json" in result["0"]:
                    data = result["0"]["json"]
                    if data and "uid" in data and data.get("uid"):
                        account_data = {
                            "email": email,
                            "password": password,
                            "phone": phone,
                            "username": username,
                            "first_name": first_name,
                            "last_name": last_name,
                            "uid": data.get("uid"),
                            "created_at": datetime.now().isoformat(),
                            "proxy": proxy
                        }
                        
                        with ACCOUNT_LOCK:
                            ACCOUNTS.append(account_data)
                            STATE["successful"] += 1
                            STATE["recent_accounts"].appendleft({
                                "email": email,
                                "username": username,
                                "uid": data.get("uid"),
                                "time": datetime.now().strftime("%H:%M:%S")
                            })
                        
                        log_sys(f"[W{worker_id}] Account created: {username}", "success", target=email, proxy=proxy)
                        return True, account_data
                    else:
                        log_sys(f"[W{worker_id}] Registration failed - no UID", "warn", target=email, proxy=proxy)
                else:
                    log_sys(f"[W{worker_id}] Unexpected response format", "warn", target=email, proxy=proxy)
            except json.JSONDecodeError:
                log_sys(f"[W{worker_id}] Invalid JSON response", "warn", target=email, proxy=proxy)
        else:
            log_sys(f"[W{worker_id}] HTTP {response.status_code}", "error", target=email, proxy=proxy)
            # If we get 400/403, proxy might be burned
            if response.status_code in [400, 403, 429]:
                with PROXY_LOCK:
                    STATE["proxies_dead"] += 1
                return False, f"HTTP {response.status_code}"
    
    except requests.exceptions.Timeout:
        log_sys(f"[W{worker_id}] Timeout", "error", target=email, proxy=proxy)
    except requests.exceptions.ConnectionError:
        log_sys(f"[W{worker_id}] Connection error", "error", target=email, proxy=proxy)
    except Exception as e:
        log_sys(f"[W{worker_id}] Error: {str(e)[:50]}", "error", target=email, proxy=proxy)
    
    with ACCOUNT_LOCK:
        STATE["failed"] += 1
    
    # Return proxy to queue for potential reuse
    return_proxy(proxy)
    return False, "Registration failed"

def account_creator_thread(worker_id):
    """Worker thread that continuously creates accounts"""
    log_sys(f"[W{worker_id}] Worker started", "info")
    
    while not STOP_CREATION.is_set():
        try:
            success, result = register_single_account(worker_id)
            
            # Update rate
            with RATE_LOCK:
                REQUEST_TIMES.append(time.time())
                if len(REQUEST_TIMES) > 1:
                    oldest = REQUEST_TIMES[0]
                    newest = REQUEST_TIMES[-1]
                    if newest - oldest > 0:
                        STATE["rate"] = len(REQUEST_TIMES) / (newest - oldest) * 60
            
            # Small delay to avoid overwhelming
            time.sleep(random.uniform(0.1, 0.3))
            
        except Exception as e:
            log_sys(f"[W{worker_id}] Worker error: {str(e)}", "error")
            time.sleep(1)

def start_creation():
    """Start the account creation process"""
    global BG_THREADS_STARTED
    
    if STATE["status"] == "running":
        return
    
    STOP_CREATION.clear()
    STATE["status"] = "running"
    STATE["start_time"] = time.time()
    STATE["start_time_str"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Start proxy manager
    threading.Thread(target=proxy_manager_thread, daemon=True).start()
    
    # Start worker threads
    for i in range(MAX_WORKERS):
        threading.Thread(target=account_creator_thread, args=(i+1,), daemon=True).start()
    
    log_sys(f"SYSTEM: Started {MAX_WORKERS} workers", "success")
    STATE["active_threads"] = MAX_WORKERS

def stop_creation():
    """Stop the account creation process"""
    STOP_CREATION.set()
    STATE["status"] = "idle"
    log_sys("SYSTEM: Stopped all workers", "info")

# ============= FLASK WEB INTERFACE =============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARENA Account Creator</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: #111;
            border: 1px solid #00ff00;
            border-radius: 10px;
            padding: 20px;
        }
        h1 {
            border-bottom: 1px solid #00ff00;
            padding-bottom: 10px;
            text-shadow: 0 0 10px #00ff00;
        }
        .stat-box {
            background: #1a1a1a;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 3px solid #00ff00;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #00ff00;
        }
        .stat-label {
            color: #888;
            font-size: 0.9em;
            text-transform: uppercase;
        }
        .success { color: #00ff00; }
        .failed { color: #ff4444; }
        .status-running { color: #00ff00; animation: blink 1s infinite; }
        .status-idle { color: #ffaa00; }
        @keyframes blink { 50% { opacity: 0; } }
        .log-container {
            max-height: 400px;
            overflow-y: auto;
            background: #000;
            border: 1px solid #333;
            padding: 10px;
            border-radius: 5px;
        }
        .log-container::-webkit-scrollbar { width: 5px; }
        .log-container::-webkit-scrollbar-track { background: #1a1a1a; }
        .log-container::-webkit-scrollbar-thumb { background: #00ff00; border-radius: 5px; }
        .account-list {
            max-height: 300px;
            overflow-y: auto;
            font-size: 0.85em;
        }
        .account-list::-webkit-scrollbar { width: 5px; }
        .account-list::-webkit-scrollbar-track { background: #1a1a1a; }
        .account-list::-webkit-scrollbar-thumb { background: #00ff00; border-radius: 5px; }
        .btn-control {
            background: #00ff00;
            color: #000;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        .btn-control:hover { background: #00cc00; color: #000; }
        .btn-danger-custom {
            background: #ff4444;
            color: #fff;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        .btn-danger-custom:hover { background: #cc0000; color: #fff; }
        .level-success { color: #00ff00; }
        .level-error { color: #ff4444; }
        .level-warn { color: #ffaa00; }
        .level-info { color: #66ccff; }
        .log-time { color: #888; }
        .badge-gmail { background: #ea4335; color: white; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ ARENA Account Creator
            <span class="badge-gmail">HIGH SPEED</span>
            <span style="float:right;font-size:0.5em;color:#888;">v1.0</span>
        </h1>
        
        <div class="row mt-3">
            <div class="col-md-4">
                <button class="btn-control w-100" id="controlBtn" onclick="toggleCreation()">
                    {{ '⏹ STOP' if stats.status == 'running' else '▶ START' }}
                </button>
            </div>
            <div class="col-md-4">
                <button class="btn-control w-100" onclick="location.reload()">⟳ REFRESH</button>
            </div>
            <div class="col-md-4">
                <button class="btn-danger-custom w-100" onclick="clearAccounts()">🗑 CLEAR</button>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">Total Attempts</div>
                    <div class="stat-value">{{ stats.total_attempts }}</div>
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
                    <div class="stat-label">Rate (accounts/min)</div>
                    <div class="stat-value">{{ "%.0f"|format(stats.rate) }}</div>
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
                    <div class="stat-label">Proxy Queue</div>
                    <div class="stat-value">{{ stats.proxies_live }}</div>
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
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <h4>Recent Accounts</h4>
                <div class="account-list">
                    <table class="table table-dark table-sm">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Username</th>
                                <th>Email</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for acc in stats.recent_accounts %}
                            <tr>
                                <td>{{ acc.time }}</td>
                                <td>{{ acc.username }}</td>
                                <td style="color:#66ccff;">{{ acc.email }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="col-md-6">
                <h4>Live Logs</h4>
                <div class="log-container">
                    {% for log in stats.logs[:50] %}
                    <div class="level-{{ log.level }}">
                        <span class="log-time">[{{ log.time }}]</span>
                        <span>{{ log.message }}</span>
                        {% if log.target and log.target != 'N/A' %}
                        <span style="color:#888;">→ {{ log.target }}</span>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <a href="/download" class="btn btn-success btn-sm">⬇ Download Accounts ({{ stats.accounts_created }})</a>
            </div>
            <div class="col-md-6 text-end">
                <span style="color:#555;font-size:0.8em;">Started: {{ stats.start_time_str }}</span>
            </div>
        </div>
    </div>
    
    <script>
        function toggleCreation() {
            fetch('/toggle', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    location.reload();
                });
        }
        
        function clearAccounts() {
            if (confirm('Delete all accounts? This cannot be undone!')) {
                fetch('/clear', { method: 'POST' })
                    .then(() => location.reload());
            }
        }
        
        // Auto refresh every 5 seconds
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>
"""

# ============= FLASK ROUTES =============
@app.route('/')
def index():
    """Main dashboard"""
    with ACCOUNT_LOCK:
        stats_copy = {
            "total_attempts": STATE["total_attempts"],
            "successful": STATE["successful"],
            "failed": STATE["failed"],
            "active_threads": STATE["active_threads"],
            "accounts_created": len(ACCOUNTS),
            "start_time_str": STATE["start_time_str"],
            "status": STATE["status"],
            "rate": STATE["rate"],
            "proxies_live": len(PROXIES_LIVE_QUEUE),
            "proxies_fetched": STATE["proxies_fetched"],
            "proxies_dead": STATE["proxies_dead"],
            "recent_accounts": list(STATE["recent_accounts"]),
            "logs": STATE["logs"][:50]
        }
    return render_template_string(HTML_TEMPLATE, stats=stats_copy)

@app.route('/stats')
def get_stats():
    """Get JSON statistics"""
    with ACCOUNT_LOCK:
        stats_copy = {
            "total_attempts": STATE["total_attempts"],
            "successful": STATE["successful"],
            "failed": STATE["failed"],
            "accounts_created": len(ACCOUNTS),
            "active_threads": STATE["active_threads"],
            "status": STATE["status"],
            "rate": STATE["rate"],
            "proxies_live": len(PROXIES_LIVE_QUEUE),
            "uptime_seconds": int(time.time() - STATE["start_time"])
        }
    return jsonify(stats_copy)

@app.route('/download')
def download_accounts():
    """Download all accounts as CSV"""
    with ACCOUNT_LOCK:
        if not ACCOUNTS:
            return "No accounts found", 404
        
        csv_data = "Email,Password,Phone,Username,FirstName,LastName,UID,CreatedAt,Proxy\n"
        for acc in ACCOUNTS:
            csv_data += f"{acc['email']},{acc['password']},{acc['phone']},{acc['username']},{acc['first_name']},{acc['last_name']},{acc.get('uid','')},{acc['created_at']},{acc.get('proxy','')}\n"
    
    return csv_data, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=arena_accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    }

@app.route('/toggle', methods=['POST'])
def toggle_creation():
    """Start/Stop account creation"""
    if STATE["status"] == "running":
        stop_creation()
        return jsonify({"status": "idle"})
    else:
        start_creation()
        return jsonify({"status": "running"})

@app.route('/clear', methods=['POST'])
def clear_accounts():
    """Clear all accounts"""
    with ACCOUNT_LOCK:
        ACCOUNTS.clear()
        STATE["total_attempts"] = 0
        STATE["successful"] = 0
        STATE["failed"] = 0
        STATE["recent_accounts"].clear()
    return jsonify({"status": "cleared"})

@app.route('/ping')
def ping():
    """Health check endpoint"""
    return jsonify({
        "status": "alive",
        "accounts": len(ACCOUNTS),
        "time": datetime.now().isoformat()
    })

# ============= MAIN =============
BG_THREADS_STARTED = False

def init_background_threads():
    """Initialize background threads"""
    global BG_THREADS_STARTED
    if not BG_THREADS_STARTED:
        start_creation()
        BG_THREADS_STARTED = True

@app.before_request
def activate_threads():
    """Ensure threads start before handling requests"""
    init_background_threads()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Start threads
    init_background_threads()
    
    # Run Flask app
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
