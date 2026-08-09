#!/usr/bin/env python3
"""
ARENA - Rebel X Arena Mass Account Creator
Combines proxy rotation with high-speed account registration
Target: Register hundreds of accounts per second
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
from collections import deque
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# ============ CONFIGURATION ============
TARGET_URL = "https://s2-api.digicroz.com/trpc/rebelXArena/webApp/rebelXArena/auth.register?batch=1"
MAX_WORKERS = 200  # Concurrent threads for registration
PROXY_BATCH_SIZE = 500
PROXY_QUEUE_MIN = 50
REGISTER_RATE_LIMIT = 0.05  # Minimum seconds between requests per worker

# ============ GLOBAL STATE ============
STATE = {
    "start_time": time.time(),
    "start_time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "total_attempts": 0,
    "successful": 0,
    "failed": 0,
    "rate_per_second": 0,
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "accounts_created": 0,
    "logs": []
}

PROXIES_LIVE_QUEUE = []
PROXY_LOCK = threading.Lock()
STATS_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
STOP_FLAG = threading.Event()

# Rate tracking
request_times = deque(maxlen=100)
RATE_LOCK = threading.Lock()

# ============ NAME GENERATORS ============
FIRST_NAMES = [
    "Raj", "Amit", "Priya", "Suresh", "Neha", "Vikram", "Anjali", "Rahul", "Pooja", "Arun",
    "Kiran", "Meena", "Sunil", "Deepa", "Manoj", "Sita", "Ravi", "Geeta", "Naveen", "Kavya",
    "Aisha", "Kabir", "Zara", "Arjun", "Mira", "Karan", "Riya", "Dev", "Sara", "Aditya",
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth",
    "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
    "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra",
    "Donald", "Donna", "Steven", "Carol", "Paul", "Ruth", "Andrew", "Sharon", "Joshua", "Michelle",
    "Vishal", "Nisha", "Gaurav", "Swati", "Anand", "Kajal", "Pankaj", "Shreya", "Deepak", "Manisha",
    "Sanjay", "Ritu", "Rajesh", "Sneha", "Rakesh", "Pallavi", "Mukesh", "Shilpa", "Bharat", "Jyoti",
    "Ashok", "Komal", "Ramesh", "Mansi", "Mahesh", "Ruchika", "Sachin", "Madhu", "Dinesh", "Simran"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Kumar", "Singh", "Reddy", "Rao", "Joshi", "Gupta", "Mehta",
    "Choudhary", "Desai", "Nair", "Menon", "Iyer", "Pillai", "Acharya", "Bhatt", "Das", "Mishra",
    "Agarwal", "Khanna", "Malhotra", "Saxena", "Tiwari", "Dubey", "Pandey", "Tripathi", "Yadav", "Jha",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green"
]

# ============ EMAIL GENERATORS ============
def generate_username():
    """Generate clean alphanumeric username"""
    patterns = [
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(100, 9999)}",
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))}{random.randint(100, 9999)}",
        lambda: f"{random.choice(FIRST_NAMES).lower()}{''.join(random.choices(string.ascii_lowercase, k=random.randint(3, 5)))}",
        lambda: f"{random.randint(10, 999)}{random.choice(FIRST_NAMES).lower()}",
        lambda: f"{random.choice(['gamer','player','winner','champion','master','pro','elite','legend','hero','star'])}{random.randint(100, 9999)}",
        lambda: f"{random.choice(FIRST_NAMES)[0].lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        lambda: f"user{random.randint(10000, 999999)}",
        lambda: f"test{random.randint(10000, 999999)}",
        lambda: f"play{random.randint(10000, 999999)}",
    ]
    return random.choice(patterns)()

def generate_email():
    """Generate unique Gmail address"""
    return f"{generate_username()}@gmail.com"

# ============ PHONE GENERATOR ============
def generate_phone():
    """Generate valid Indian phone number"""
    return f"{random.choice(['6','7','8','9'])}{''.join(random.choices(string.digits, k=9))}"

# ============ PASSWORD GENERATOR ============
def generate_password():
    """Generate strong password with special chars"""
    length = random.randint(12, 18)
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-=<>?"
    return ''.join(random.choices(chars, k=length))

# ============ PROXY MANAGEMENT (from main.py) ============
def fetch_raw_proxies():
    """Fetch proxies from multiple sources"""
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
    ]
    
    raw_proxies = set()
    log_sys("SYSTEM: Fetching proxies from global sources...", "info")
    
    for url in sources:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                for line in resp.text.strip().split('\n'):
                    proxy = line.strip()
                    if ":" in proxy:
                        raw_proxies.add(proxy)
        except Exception as e:
            log_sys(f"SYSTEM: Failed to fetch from {url} - {str(e)}", "warn")
    
    proxy_list = list(raw_proxies)
    random.shuffle(proxy_list)
    return proxy_list[:PROXY_BATCH_SIZE]

def check_single_proxy(proxy):
    """Validate proxy is alive"""
    proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    try:
        res = requests.get("http://connectivitycheck.gstatic.com/generate_204", proxies=proxies, timeout=5)
        if res.status_code == 204:
            with PROXY_LOCK:
                PROXIES_LIVE_QUEUE.append(proxy)
            with STATS_LOCK:
                STATE["proxies_live"] += 1
            log_sys(f"VALIDATED: Proxy is ALIVE", "success", proxy=proxy)
            return True
        else:
            with STATS_LOCK:
                STATE["proxies_dead"] += 1
            return False
    except:
        with STATS_LOCK:
            STATE["proxies_dead"] += 1
        return False

def proxy_manager_thread():
    """Background thread to maintain proxy queue"""
    while not STOP_FLAG.is_set():
        with PROXY_LOCK:
            queue_size = len(PROXIES_LIVE_QUEUE)
        
        if queue_size < PROXY_QUEUE_MIN:
            log_sys(f"SYSTEM: Proxy queue low ({queue_size}). Fetching new proxies...", "info")
            new_proxies = fetch_raw_proxies()
            
            with STATS_LOCK:
                STATE["proxies_fetched"] += len(new_proxies)
            
            log_sys(f"SYSTEM: Downloaded {len(new_proxies)} proxies. Validating...", "info")
            
            # Validate proxies in parallel
            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = [executor.submit(check_single_proxy, proxy) for proxy in new_proxies]
                for future in as_completed(futures):
                    pass  # Results are already logged
            
            with PROXY_LOCK:
                log_sys(f"SYSTEM: Proxy queue now has {len(PROXIES_LIVE_QUEUE)} live proxies", "success")
        
        time.sleep(5)

# ============ ACCOUNT REGISTRATION (from playt24.py adapted) ============
def register_single_account(worker_id):
    """Register a single account using a proxy from the queue"""
    # Get a proxy from the queue
    with PROXY_LOCK:
        if not PROXIES_LIVE_QUEUE:
            return False, "No proxies available"
        proxy = PROXIES_LIVE_QUEUE.pop(0)
    
    # Generate account data
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    username = generate_username()
    phone = generate_phone()
    email = generate_email()
    password = generate_password()
    
    # Build request payload
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
    
    # Headers with rotating user-agent
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://web-app.rebelxarena.com",
        "referer": "https://web-app.rebelxarena.com/",
        "sec-ch-ua": "\"Not=A?Brand\";v=\"99\", \"Google Chrome\";v=\"151\", \"Chromium\";v=\"151\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Linux\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": random.choice([
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0"
        ])
    }
    
    # Proxy config
    proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    
    try:
        # Rate limiting
        time.sleep(REGISTER_RATE_LIMIT)
        
        response = requests.post(TARGET_URL, headers=headers, json=payload, proxies=proxy_dict, timeout=10)
        
        # Track rate
        with RATE_LOCK:
            request_times.append(time.time())
        
        # Parse response
        try:
            result = response.json()
            
            # Check for success - look for uid or success indicators
            if response.status_code == 200:
                # tRPC response format
                data = result.get("0", {})
                json_data = data.get("json", {})
                
                # Check for successful registration
                if "result" in json_data or json_data.get("success") is not False:
                    with STATS_LOCK:
                        STATE["successful"] += 1
                        STATE["total_attempts"] += 1
                        STATE["accounts_created"] += 1
                    
                    log_sys(f"[W{worker_id}] ✅ Account created: {username} ({email})", "success", proxy=proxy)
                    return True, {"username": username, "email": email, "password": password, "phone": phone}
                else:
                    # Check for specific errors
                    error_msg = str(result)
                    with STATS_LOCK:
                        STATE["failed"] += 1
                        STATE["total_attempts"] += 1
                    
                    log_sys(f"[W{worker_id}] ❌ Registration failed: {error_msg[:100]}", "error", proxy=proxy)
                    return False, error_msg
            else:
                with STATS_LOCK:
                    STATE["failed"] += 1
                    STATE["total_attempts"] += 1
                
                log_sys(f"[W{worker_id}] ❌ HTTP {response.status_code}: {response.text[:100]}", "error", proxy=proxy)
                return False, f"HTTP {response.status_code}"
                
        except json.JSONDecodeError:
            with STATS_LOCK:
                STATE["failed"] += 1
                STATE["total_attempts"] += 1
            log_sys(f"[W{worker_id}] ❌ Invalid JSON response: {response.text[:100]}", "error", proxy=proxy)
            return False, "Invalid JSON"
            
    except requests.exceptions.Timeout:
        with STATS_LOCK:
            STATE["failed"] += 1
            STATE["total_attempts"] += 1
        log_sys(f"[W{worker_id}] ⏱️ Request timeout", "warn", proxy=proxy)
        return False, "Timeout"
        
    except requests.exceptions.ProxyError:
        with STATS_LOCK:
            STATE["failed"] += 1
            STATE["total_attempts"] += 1
        log_sys(f"[W{worker_id}] 🚫 Proxy error - marking as dead", "error", proxy=proxy)
        return False, "Proxy error"
        
    except Exception as e:
        with STATS_LOCK:
            STATE["failed"] += 1
            STATE["total_attempts"] += 1
        log_sys(f"[W{worker_id}] ❌ Error: {str(e)}", "error", proxy=proxy)
        return False, str(e)

def worker_thread(worker_id):
    """Worker thread that continuously registers accounts"""
    log_sys(f"SYSTEM: Worker {worker_id} started", "info")
    
    while not STOP_FLAG.is_set():
        try:
            success, result = register_single_account(worker_id)
            
            # If proxy is dead or no proxies, wait a moment
            if not success and "no proxies" in str(result).lower():
                time.sleep(1)
                
        except Exception as e:
            log_sys(f"[W{worker_id}] Worker error: {str(e)}", "error")
            time.sleep(1)

# ============ LOGGING ============
def log_sys(msg, level="info", target="N/A", proxy="N/A"):
    """Thread-safe logging"""
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

# ============ FLASK WEB INTERFACE ============
def init_background_threads():
    """Initialize all background threads"""
    log_sys("SYSTEM: Initializing background threads...", "info")
    
    # Start proxy manager
    threading.Thread(target=proxy_manager_thread, daemon=True).start()
    
    # Start workers
    for i in range(MAX_WORKERS):
        threading.Thread(target=worker_thread, args=(i+1,), daemon=True).start()
    
    log_sys(f"SYSTEM: Started {MAX_WORKERS} worker threads", "success")

@app.before_request
def activate_threads():
    """Ensure threads start with Flask"""
    if not hasattr(app, '_threads_started'):
        init_background_threads()
        app._threads_started = True

@app.route('/')
def index():
    """Main dashboard"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/stats')
def stats():
    """Get current statistics"""
    with STATS_LOCK:
        stats_data = {
            "uptime": f"{int(time.time() - STATE['start_time'])}s",
            "started_at": STATE["start_time_str"],
            "total_attempts": STATE["total_attempts"],
            "successful": STATE["successful"],
            "failed": STATE["failed"],
            "rate_per_second": calculate_rate(),
            "proxies_fetched": STATE["proxies_fetched"],
            "proxies_dead": STATE["proxies_dead"],
            "proxies_live_queue": len(PROXIES_LIVE_QUEUE),
            "accounts_created": STATE["accounts_created"],
            "logs": STATE["logs"][:100]
        }
    return jsonify(stats_data)

def calculate_rate():
    """Calculate registration rate per second"""
    with RATE_LOCK:
        if len(request_times) < 2:
            return 0
        oldest = request_times[0]
        newest = request_times[-1]
        if newest - oldest > 0:
            return len(request_times) / (newest - oldest)
    return 0

@app.route('/api/start', methods=['POST'])
def start_creation():
    """Start account creation"""
    STOP_FLAG.clear()
    return jsonify({"status": "started"})

@app.route('/api/stop', methods=['POST'])
def stop_creation():
    """Stop account creation"""
    STOP_FLAG.set()
    return jsonify({"status": "stopped"})

@app.route('/api/reset', methods=['POST'])
def reset_stats():
    """Reset all statistics"""
    with STATS_LOCK:
        STATE["total_attempts"] = 0
        STATE["successful"] = 0
        STATE["failed"] = 0
        STATE["accounts_created"] = 0
    return jsonify({"status": "reset"})

# ============ HTML TEMPLATE ============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARENA - Rebel X Arena Account Creator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', Courier, monospace;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        
        h1 {
            text-align: center;
            color: #ff6b35;
            text-shadow: 0 0 30px rgba(255,107,53,0.3);
            border-bottom: 2px solid #ff6b35;
            padding-bottom: 15px;
            margin-bottom: 20px;
            font-size: 2.5em;
            letter-spacing: 4px;
        }
        .subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 20px;
            font-size: 0.9em;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: rgba(0,255,0,0.03);
            border: 1px solid #00ff00;
            padding: 15px;
            text-align: center;
        }
        .stat-box .label { font-size: 0.7em; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        .stat-box .value { font-size: 1.8em; font-weight: bold; margin-top: 5px; }
        .stat-box .value.green { color: #00ff00; }
        .stat-box .value.red { color: #ff3333; }
        .stat-box .value.orange { color: #ff6b35; }
        .stat-box .value.cyan { color: #00ddff; }
        .stat-box .value.purple { color: #aa66ff; }
        
        .controls {
            display: flex;
            gap: 10px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 30px;
            border: none;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn-start { background: #00ff00; color: #000; }
        .btn-start:hover { box-shadow: 0 0 20px rgba(0,255,0,0.5); transform: scale(1.02); }
        .btn-stop { background: #ff3333; color: #fff; }
        .btn-stop:hover { box-shadow: 0 0 20px rgba(255,51,51,0.5); transform: scale(1.02); }
        .btn-reset { background: #333; color: #fff; }
        .btn-reset:hover { background: #555; }
        
        .logs {
            background: #000;
            border: 1px solid #00ff00;
            height: 500px;
            overflow-y: auto;
            padding: 10px;
            margin-top: 20px;
        }
        .logs::-webkit-scrollbar { width: 8px; }
        .logs::-webkit-scrollbar-track { background: #0a0a0a; }
        .logs::-webkit-scrollbar-thumb { background: #00ff00; border-radius: 4px; }
        
        .log-entry {
            padding: 3px 0;
            border-bottom: 1px solid rgba(0,255,0,0.05);
            font-size: 0.8em;
            display: flex;
            gap: 10px;
        }
        .log-entry .time { color: #666; min-width: 70px; }
        .log-entry .message { flex: 1; }
        .log-entry .proxy { color: #888; min-width: 120px; font-size: 0.8em; }
        
        .level-success { color: #00ff00; }
        .level-error { color: #ff3333; }
        .level-warn { color: #ffaa00; }
        .level-info { color: #aaa; }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }
        .status-running { background: #00ff00; box-shadow: 0 0 10px rgba(0,255,0,0.5); animation: pulse 1s infinite; }
        .status-stopped { background: #ff3333; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        
        @media (max-width: 600px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            h1 { font-size: 1.5em; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ ARENA</h1>
        <div class="subtitle">Rebel X Arena Mass Account Creator | Gmail Only | Proxy Rotated</div>
        
        <div style="margin-bottom: 15px; font-size: 1.1em;">
            <span class="status-indicator" id="statusIndicator"></span>
            <span id="statusText">Checking...</span>
            <span style="float:right;color:#888;" id="rateDisplay">Rate: 0 accounts/sec</span>
        </div>
        
        <div class="stats-grid" id="statsGrid">
            <div class="stat-box">
                <div class="label">Total Attempts</div>
                <div class="value green" id="val_total">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Successful</div>
                <div class="value green" id="val_success">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Failed</div>
                <div class="value red" id="val_failed">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Accounts Created</div>
                <div class="value orange" id="val_created">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Live Proxies</div>
                <div class="value cyan" id="val_proxies">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Uptime</div>
                <div class="value purple" id="val_uptime">0s</div>
            </div>
        </div>
        
        <div class="controls">
            <button class="btn btn-start" id="btnStart">▶ Start</button>
            <button class="btn btn-stop" id="btnStop">⏹ Stop</button>
            <button class="btn btn-reset" id="btnReset">⟳ Reset Stats</button>
        </div>
        
        <div class="logs" id="logContainer">
            <div id="logEntries"></div>
        </div>
    </div>
    
    <script>
        let isRunning = true;
        let autoScroll = true;
        
        const logContainer = document.getElementById('logContainer');
        const logEntries = document.getElementById('logEntries');
        
        function fetchStats() {
            fetch('/api/stats')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('val_total').textContent = data.total_attempts;
                    document.getElementById('val_success').textContent = data.successful;
                    document.getElementById('val_failed').textContent = data.failed;
                    document.getElementById('val_created').textContent = data.accounts_created;
                    document.getElementById('val_proxies').textContent = data.proxies_live_queue;
                    document.getElementById('val_uptime').textContent = data.uptime;
                    document.getElementById('rateDisplay').textContent = `Rate: ${data.rate_per_second.toFixed(1)} accounts/sec`;
                    
                    // Update status
                    const indicator = document.getElementById('statusIndicator');
                    const statusText = document.getElementById('statusText');
                    if (data.total_attempts > 0) {
                        indicator.className = 'status-indicator status-running';
                        statusText.textContent = 'RUNNING';
                    } else {
                        indicator.className = 'status-indicator status-stopped';
                        statusText.textContent = 'STOPPED';
                    }
                    
                    // Update logs
                    if (data.logs && data.logs.length > 0) {
                        let html = '';
                        data.logs.forEach(log => {
                            html += `
                                <div class="log-entry level-${log.level}">
                                    <span class="time">${log.time}</span>
                                    <span class="message">${log.message}</span>
                                    <span class="proxy">${log.proxy}</span>
                                </div>
                            `;
                        });
                        logEntries.innerHTML = html;
                        
                        if (autoScroll) {
                            logContainer.scrollTop = 0;
                        }
                    }
                })
                .catch(err => console.error('Stats error:', err));
        }
        
        function control(action) {
            fetch(`/api/${action}`, { method: 'POST' })
                .then(() => setTimeout(fetchStats, 500));
        }
        
        document.getElementById('btnStart').addEventListener('click', () => control('start'));
        document.getElementById('btnStop').addEventListener('click', () => control('stop'));
        document.getElementById('btnReset').addEventListener('click', () => {
            if (confirm('Reset all statistics?')) control('reset');
        });
        
        // Auto-scroll toggle on click
        logContainer.addEventListener('click', () => {
            autoScroll = !autoScroll;
        });
        
        // Update every 1 second
        setInterval(fetchStats, 1000);
        fetchStats();
    </script>
</body>
</html>
"""

# ============ MAIN ============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Start threads
    init_background_threads()
    
    # Run Flask
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
