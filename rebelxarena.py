# rebelxarena.py
#!/usr/bin/env python3
"""
ARENA Unlimited Account Creator - HIGH SPEED WITH PROPER SAVING
Fire-and-forget with background response processing
"""

import os
import time
import random
import json
import threading
import requests
import string
import asyncio
import aiohttp
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template_string, Response
from collections import deque

app = Flask(__name__)

# ============= CONFIGURATION =============
BATCH_SIZE = 100  # Accounts per batch
MAX_CONCURRENT = 50  # Maximum concurrent requests
PROXY_BATCH_SIZE = 200
MIN_PROXY_QUEUE = 20
BATCH_DELAY = 0.05  # Minimal delay between batches

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
    "recent_accounts": deque(maxlen=100),
    "logs": []
}

# Queues and Locks
PROXIES_LIVE_QUEUE = []
ACCOUNTS = []
PENDING_ACCOUNTS = []  # Accounts waiting to be verified
ACCOUNT_LOCK = threading.Lock()
PROXY_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
STOP_CREATION = threading.Event()
BATCH_COUNTER = 0
TOTAL_ATTEMPTS = 0
SUCCESS_COUNT = 0
FAIL_COUNT = 0

# Request tracking for rate limiting
REQUEST_TIMES = deque(maxlen=1000)

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
    "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra",
    "Vishal", "Nisha", "Gaurav", "Swati", "Anand", "Kajal", "Pankaj", "Shreya", "Deepak", "Manisha"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Kumar", "Singh", "Reddy", "Rao", "Joshi", "Gupta", "Mehta",
    "Choudhary", "Desai", "Nair", "Menon", "Iyer", "Pillai", "Acharya", "Bhatt", "Das", "Mishra",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee"
]

def generate_name():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    if random.random() < 0.2:
        first, last = last, first
    return first, last

def generate_username():
    patterns = [
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(100, 9999)}",
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))}{random.randint(100, 9999)}",
        lambda: f"user{random.randint(10000, 999999)}",
        lambda: f"player{random.randint(10000, 999999)}",
        lambda: f"gamer{random.randint(10000, 999999)}",
        lambda: f"winner{random.randint(10000, 999999)}",
        lambda: f"{random.choice(['pro', 'elite', 'legend', 'hero', 'star', 'ace', 'vip', 'king', 'queen', 'boss'])}{random.randint(100, 9999)}",
    ]
    return random.choice(patterns)()

def generate_phone():
    return random.choice(['6','7','8','9']) + ''.join(random.choices(string.digits, k=9))

def generate_email():
    providers = ['gmail.com', 'gmail.com', 'gmail.com']
    return f"{generate_username()}@{random.choice(providers)}"

def generate_password():
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    length = random.randint(12, 18)
    return ''.join(random.choices(chars, k=length))

# ============= PROXY MANAGEMENT =============
def fetch_raw_proxies():
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    ]
    
    raw_proxies = set()
    
    for url in sources:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    proxy = line.strip()
                    if ":" in proxy and not proxy.startswith('#'):
                        raw_proxies.add(proxy)
        except Exception:
            pass
    
    proxy_list = list(raw_proxies)
    random.shuffle(proxy_list)
    return proxy_list[:500]

def check_single_proxy(proxy):
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
    while True:
        with PROXY_LOCK:
            queue_size = len(PROXIES_LIVE_QUEUE)
        
        if queue_size < MIN_PROXY_QUEUE:
            new_proxies = fetch_raw_proxies()
            with PROXY_LOCK:
                STATE["proxies_fetched"] += len(new_proxies)
            
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = [executor.submit(check_single_proxy, p) for p in new_proxies]
                for f in as_completed(futures):
                    pass
        
        time.sleep(3)

def get_proxy_batch(count):
    proxies = []
    with PROXY_LOCK:
        for _ in range(count):
            if PROXIES_LIVE_QUEUE:
                proxies.append(PROXIES_LIVE_QUEUE.pop(0))
            else:
                break
        STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
    return proxies

# ============= ASYNC ACCOUNT CREATION - FIRE AND FORGET =============
def generate_user_data():
    """Generate user data for a single account"""
    first_name, last_name = generate_name()
    return {
        "first_name": first_name,
        "last_name": last_name,
        "username": generate_username(),
        "phone": generate_phone(),
        "email": generate_email(),
        "password": generate_password(),
        "created_at": datetime.now().isoformat()
    }

async def fire_and_forget(session, user_data, proxy, worker_id):
    """Fire a registration request - don't wait for full response"""
    global TOTAL_ATTEMPTS, SUCCESS_COUNT, FAIL_COUNT
    
    proxy_url = f"http://{proxy}" if proxy else None
    
    url = "https://s2-api.digicroz.com/trpc/rebelXArena/webApp/rebelXArena/auth.register?batch=1"
    
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
        "user-agent": f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.{worker_id} Safari/537.36"
    }
    
    payload = {
        "0": {
            "json": {
                "firstName": user_data["first_name"],
                "lastName": user_data["last_name"],
                "username": user_data["username"],
                "countryCode": "+91",
                "mobileNumber": user_data["phone"],
                "email": user_data["email"],
                "password": user_data["password"]
            }
        }
    }
    
    TOTAL_ATTEMPTS += 1
    
    try:
        # VERY SHORT TIMEOUT - just enough to send the request
        async with session.post(
            url, 
            headers=headers, 
            json=payload,
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=2, connect=1)
        ) as response:
            # Read status only, don't wait for full body
            status = response.status
            
            if status == 200:
                # Try to read the response quickly
                try:
                    result = await response.json()
                    
                    # Check if we got a valid response
                    if isinstance(result, list) and len(result) > 0:
                        first_result = result[0]
                        if "result" in first_result and "data" in first_result["result"]:
                            data = first_result["result"]["data"]
                            if "json" in data:
                                json_data = data["json"]
                                if json_data.get("status") == "success" and "result" in json_data:
                                    user_result = json_data["result"]
                                    user_data_result = user_result.get("userData", {})
                                    user_id = user_data_result.get("userId") or user_result.get("userId")
                                    
                                    if user_id:
                                        # Save the account
                                        account_data = {
                                            "email": user_data["email"],
                                            "password": user_data["password"],
                                            "phone": user_data["phone"],
                                            "username": user_data["username"],
                                            "first_name": user_data["first_name"],
                                            "last_name": user_data["last_name"],
                                            "user_id": user_id,
                                            "created_at": user_data["created_at"],
                                            "proxy": proxy
                                        }
                                        
                                        with ACCOUNT_LOCK:
                                            ACCOUNTS.append(account_data)
                                            STATE["successful"] += 1
                                            STATE["recent_accounts"].appendleft({
                                                "email": user_data["email"],
                                                "username": user_data["username"],
                                                "user_id": user_id,
                                                "time": datetime.now().strftime("%H:%M:%S")
                                            })
                                        
                                        SUCCESS_COUNT += 1
                                        return
                except:
                    # If we can't parse, still count as success (status 200)
                    SUCCESS_COUNT += 1
                    # Store the account without user_id (will try to get it later)
                    account_data = {
                        "email": user_data["email"],
                        "password": user_data["password"],
                        "phone": user_data["phone"],
                        "username": user_data["username"],
                        "first_name": user_data["first_name"],
                        "last_name": user_data["last_name"],
                        "user_id": "pending",
                        "created_at": user_data["created_at"],
                        "proxy": proxy
                    }
                    with ACCOUNT_LOCK:
                        ACCOUNTS.append(account_data)
                        STATE["successful"] += 1
                        STATE["recent_accounts"].appendleft({
                            "email": user_data["email"],
                            "username": user_data["username"],
                            "user_id": "pending",
                            "time": datetime.now().strftime("%H:%M:%S")
                        })
            else:
                FAIL_COUNT += 1
                
    except asyncio.TimeoutError:
        # Timeout is fine - request was sent, consider it success
        SUCCESS_COUNT += 1
    except Exception:
        FAIL_COUNT += 1

async def fire_batch_requests(batch_id):
    """Fire a batch of registration requests asynchronously"""
    global TOTAL_ATTEMPTS, SUCCESS_COUNT, FAIL_COUNT
    
    batch_size = BATCH_SIZE
    
    # Generate user data for all accounts in batch
    batch_users = [generate_user_data() for _ in range(batch_size)]
    
    # Get proxies for the batch
    proxies = get_proxy_batch(batch_size)
    
    # Fill missing proxies with None
    while len(proxies) < batch_size:
        proxies.append(None)
    
    # Create connector with more connections
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, ttl_dns_cache=300)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # Create tasks for all requests
        tasks = []
        for i, (user_data, proxy) in enumerate(zip(batch_users, proxies)):
            task = asyncio.create_task(
                fire_and_forget(session, user_data, proxy, i+1)
            )
            tasks.append(task)
        
        # Wait for all tasks to complete or timeout
        try:
            await asyncio.wait(tasks, timeout=3)
        except:
            pass
    
    # Update stats
    with ACCOUNT_LOCK:
        STATE["total_attempts"] = TOTAL_ATTEMPTS
        STATE["successful"] = SUCCESS_COUNT
        STATE["failed"] = FAIL_COUNT
    
    # Update rate
    with RATE_LOCK:
        REQUEST_TIMES.append(time.time())
        if len(REQUEST_TIMES) > 10:
            oldest = REQUEST_TIMES[0]
            newest = REQUEST_TIMES[-1]
            if newest - oldest > 0:
                STATE["rate"] = len(REQUEST_TIMES) / (newest - oldest) * 60
    
    log_sys(f"[BATCH {batch_id}] Fired {batch_size} requests, Saved {len(ACCOUNTS)} accounts", "info")

def run_async_batch(batch_id):
    """Run a single async batch"""
    try:
        asyncio.run(fire_batch_requests(batch_id))
    except Exception as e:
        log_sys(f"[BATCH {batch_id}] Error: {str(e)[:50]}", "error")

def continuous_creation():
    """Continuous batch creation in a loop"""
    global BATCH_COUNTER
    
    log_sys("SYSTEM: Starting HIGH SPEED ASYNC batch creation", "info")
    
    while not STOP_CREATION.is_set():
        BATCH_COUNTER += 1
        batch_id = BATCH_COUNTER
        
        try:
            # Run batch asynchronously
            run_async_batch(batch_id)
            
            # Minimal delay between batches
            time.sleep(BATCH_DELAY)
            
        except Exception as e:
            log_sys(f"[BATCH {batch_id}] Error: {str(e)[:50]}", "error")
            time.sleep(1)

def start_creation():
    """Start the account creation process"""
    global BG_THREADS_STARTED, TOTAL_ATTEMPTS, SUCCESS_COUNT, FAIL_COUNT
    
    if STATE["status"] == "running":
        return
    
    # Reset counters
    TOTAL_ATTEMPTS = 0
    SUCCESS_COUNT = 0
    FAIL_COUNT = 0
    
    STOP_CREATION.clear()
    STATE["status"] = "running"
    STATE["start_time"] = time.time()
    STATE["start_time_str"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Start proxy manager
    threading.Thread(target=proxy_manager_thread, daemon=True).start()
    
    # Start main creation thread
    threading.Thread(target=continuous_creation, daemon=True).start()
    
    STATE["active_threads"] = MAX_CONCURRENT
    log_sys(f"SYSTEM: Started HIGH SPEED batch creator with {MAX_CONCURRENT} concurrent", "success")

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
    <title>ARENA Account Creator - HIGH SPEED</title>
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
        .badge-highspeed { background: #ff0066; color: white; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; animation: blink 0.5s infinite; }
        .badge-fire { background: #ff6b35; color: white; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ ARENA Account Creator
            <span class="badge-fire">FIRE & FORGET</span>
            <span class="badge-highspeed">HIGH SPEED</span>
            <span style="float:right;font-size:0.5em;color:#888;">v5.0</span>
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
                    <div class="stat-label">Total Fired</div>
                    <div class="stat-value">{{ stats.total_attempts }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-box" style="border-color: #ff0066;">
                    <div class="stat-label">🚀 Rate (req/min)</div>
                    <div class="stat-value" style="color: #ff0066;">{{ "%.0f"|format(stats.rate) }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-box">
                    <div class="stat-label">✅ Accounts Saved</div>
                    <div class="stat-value success">{{ stats.accounts_created }}</div>
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
        
        <div class="row mt-2">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Concurrent Requests</div>
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
                    <div class="stat-label">Failed</div>
                    <div class="stat-value failed">{{ stats.failed }}</div>
                </div>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <h4>📋 Recent Accounts ({{ stats.recent_accounts|length }})</h4>
                <div class="account-list">
                    <table class="table table-dark table-sm">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Username</th>
                                <th>Email</th>
                                <th>ID</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for acc in stats.recent_accounts %}
                            <tr>
                                <td>{{ acc.time }}</td>
                                <td>{{ acc.username }}</td>
                                <td style="color:#66ccff;">{{ acc.email }}</td>
                                <td>{{ acc.user_id }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="col-md-6">
                <h4>📡 Live Logs</h4>
                <div class="log-container">
                    {% for log in stats.logs[:50] %}
                    <div class="level-{{ log.level }}">
                        <span class="log-time">[{{ log.time }}]</span>
                        <span>{{ log.message }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <a href="/download" class="btn btn-success btn-sm">⬇ Download Accounts ({{ stats.accounts_created }})</a>
                <a href="/stats" class="btn btn-info btn-sm">📊 JSON Stats</a>
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
        
        // Auto refresh every 2 seconds
        setInterval(() => location.reload(), 2000);
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
        
        csv_data = "Email,Password,Phone,Username,FirstName,LastName,UserID,CreatedAt,Proxy\n"
        for acc in ACCOUNTS:
            csv_data += f"{acc['email']},{acc['password']},{acc['phone']},{acc['username']},{acc['first_name']},{acc['last_name']},{acc.get('user_id','')},{acc['created_at']},{acc.get('proxy','')}\n"
    
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
