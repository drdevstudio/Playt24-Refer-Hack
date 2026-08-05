#!/usr/bin/env python3
"""
PLAYT24 Unlimited Account Creator - Gmail Only
Deployed on Render with Flask Web Interface
All emails are @gmail.com with clean alphanumeric usernames
"""

import requests
import random
import string
import time
import threading
import json
import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from collections import deque

app = Flask(__name__)

# Configuration
BASE_URL = "https://playt24.com"
REFERRAL_CODES = ["CBA14991"]

# Statistics
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
used_emails = set()
email_lock = threading.Lock()

# Rate limiting
request_times = deque(maxlen=100)
rate_lock = threading.Lock()

# Stop flag
stop_creation = threading.Event()

# ============= NAME GENERATORS =============

FIRST_NAMES = [
    # Indian Names
    "Raj", "Amit", "Priya", "Suresh", "Neha", "Vikram", "Anjali", "Rahul", "Pooja", "Arun",
    "Kiran", "Meena", "Sunil", "Deepa", "Manoj", "Sita", "Ravi", "Geeta", "Naveen", "Kavya",
    "Aisha", "Kabir", "Zara", "Arjun", "Mira", "Karan", "Riya", "Dev", "Sara", "Aditya",
    "Vanya", "Ishaan", "Anya", "Rohan", "Kiya", "Aarav", "Diya", "Reyansh", "Myra", "Atharv",
    "Aryan", "Ishita", "Dhruv", "Riddhi", "Krish", "Anika", "Shaurya", "Saanvi", "Vivaan", "Myra",
    # Western Names
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth",
    "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
    "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra",
    "Donald", "Donna", "Steven", "Carol", "Paul", "Ruth", "Andrew", "Sharon", "Joshua", "Michelle",
    "Kenneth", "Laura", "Kevin", "Sarah", "Brian", "Kimberly", "George", "Deborah", "Timothy", "Amy",
    "Ronald", "Angela", "Edward", "Melissa", "Jason", "Brenda", "Jeffrey", "Anna", "Ryan", "Rebecca",
    "Jacob", "Virginia", "Gary", "Kathleen", "Nicholas", "Pamela", "Eric", "Martha", "Jonathan", "Amanda",
    "Stephen", "Stephanie", "Larry", "Carolyn", "Justin", "Christine", "Scott", "Marie", "Brandon", "Janet",
    "Benjamin", "Catherine", "Samuel", "Frances", "Gregory", "Ann", "Alexander", "Joyce", "Patrick", "Diane",
    "Jack", "Alice", "Dennis", "Julie", "Jerry", "Heather", "Tyler", "Teresa", "Aaron", "Doris",
    "Jose", "Gloria", "Nathan", "Evelyn", "Adam", "Jean", "Henry", "Cheryl", "Zachary", "Mildred",
    # More Indian Names
    "Vishal", "Nisha", "Gaurav", "Swati", "Anand", "Kajal", "Pankaj", "Shreya", "Deepak", "Manisha",
    "Sanjay", "Ritu", "Rajesh", "Sneha", "Rakesh", "Pallavi", "Mukesh", "Shilpa", "Bharat", "Jyoti",
    "Ashok", "Komal", "Ramesh", "Mansi", "Mahesh", "Ruchika", "Sachin", "Madhu", "Dinesh", "Simran",
    "Pradeep", "Mona", "Nitin", "Ruchi", "Alok", "Suman", "Vivek", "Ranjana", "Ajay", "Shakti",
    "Sandeep", "Aarti", "Vinod", "Gita", "Jitendra", "Anita", "Shashi", "Usha", "Murari", "Babita"
]

LAST_NAMES = [
    # Indian Last Names
    "Sharma", "Verma", "Patel", "Kumar", "Singh", "Reddy", "Rao", "Joshi", "Gupta", "Mehta",
    "Choudhary", "Desai", "Nair", "Menon", "Iyer", "Pillai", "Acharya", "Bhatt", "Das", "Mishra",
    "Agarwal", "Khanna", "Malhotra", "Saxena", "Tiwari", "Dubey", "Pandey", "Tripathi", "Yadav", "Jha",
    "Srivastava", "Vyas", "Shukla", "Upadhyay", "Bajaj", "Goel", "Jain", "Arora", "Chopra", "Kaur",
    # Western Last Names
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Turner",
    "Phillips", "Evans", "Collins", "Edwards", "Stewart", "Morris", "Murphy", "Cook", "Rogers", "Morgan",
    "Peterson", "Cooper", "Reed", "Bailey", "Bell", "Howard", "Ward", "Cox", "Diaz", "Richardson",
    "Wood", "Watson", "Brooks", "Bennett", "Gray", "James", "Reyes", "Cruz", "Hughes", "Price",
    "Myers", "Long", "Foster", "Sanders", "Ross", "Powell", "Sullivan", "Russell", "Ortiz", "Jenkins",
    "Perry", "Butler", "Barnes", "Fisher", "Henderson", "Coleman", "Simmons", "Patterson", "Jordan", "Reynolds",
    "Hamilton", "Graham", "Kim", "Gonzales", "Alexander", "Ramos", "Wallace", "Griffin", "West", "Cole",
    "Hayes", "Chavez", "Gibson", "Bryant", "Ellis", "Stevens", "Murray", "Ford", "Marshall", "Owens"
]

# ============= CLEAN EMAIL GENERATORS (NO SPECIAL CHARACTERS) =============

def generate_clean_username():
    """
    Generate clean alphanumeric username for Gmail
    Only letters (a-z) and numbers (0-9) - no dots, plus, or special chars
    """
    patterns = [
        # Pattern 1: word + number (e.g., john12345)
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(10, 9999)}",
        
        # Pattern 2: word + word + number (e.g., johnsmith123)
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        
        # Pattern 3: random letters + number (e.g., abcdef123)
        lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))}{random.randint(100, 9999)}",
        
        # Pattern 4: word + random letters (e.g., johnabc)
        lambda: f"{random.choice(FIRST_NAMES).lower()}{''.join(random.choices(string.ascii_lowercase, k=random.randint(3, 5)))}",
        
        # Pattern 5: number + word (e.g., 123john)
        lambda: f"{random.randint(10, 999)}{random.choice(FIRST_NAMES).lower()}",
        
        # Pattern 6: full word + number (e.g., gamingking123)
        lambda: f"{random.choice(['gamer', 'player', 'winner', 'champion', 'master', 'pro', 'elite', 'legend', 'hero', 'star', 'ace', 'vip', 'king', 'queen', 'boss', 'play', 'game', 'win', 'cash', 'prize', 'battle', 'arena', 'royal', 'prime', 'ultra', 'max', 'super', 'mega', 'grand'])}{random.randint(100, 9999)}",
        
        # Pattern 7: first letter + last name + number (e.g., jsmith123)
        lambda: f"{random.choice(FIRST_NAMES)[0].lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        
        # Pattern 8: two words combined (e.g., johnsmith)
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.choice(LAST_NAMES).lower()}{random.randint(10, 999)}",
        
        # Pattern 9: random numbers + letters (e.g., 123abc456)
        lambda: f"{random.randint(100, 999)}{''.join(random.choices(string.ascii_lowercase, k=random.randint(3, 5)))}{random.randint(10, 99)}",
        
        # Pattern 10: year based (e.g., john2024)
        lambda: f"{random.choice(FIRST_NAMES).lower()}{random.randint(2020, 2026)}",
        
        # Pattern 11: simple random (e.g., user123456)
        lambda: f"user{random.randint(10000, 999999)}",
        
        # Pattern 12: test based (e.g., test123456)
        lambda: f"test{random.randint(10000, 999999)}",
        
        # Pattern 13: play based (e.g., play123456)
        lambda: f"play{random.randint(10000, 999999)}",
        
        # Pattern 14: win based (e.g., win123456)
        lambda: f"win{random.randint(10000, 999999)}",
        
        # Pattern 15: game based (e.g., game123456)
        lambda: f"game{random.randint(10000, 999999)}",
        
        # Pattern 16: cash based (e.g., cash123456)
        lambda: f"cash{random.randint(10000, 999999)}",
    ]
    
    return random.choice(patterns)()

def generate_unique_gmail():
    """
    Generate a unique @gmail.com email with clean alphanumeric username
    No dots, no plus signs, no special characters
    """
    with email_lock:
        while True:
            username = generate_clean_username()
            email = f"{username}@gmail.com"
            
            # Ensure email is unique
            if email not in used_emails:
                used_emails.add(email)
                return email

# ============= PHONE NUMBER GENERATORS =============

def generate_phone():
    """Generate valid Indian phone number"""
    first = random.choice(['6','7','8','9'])
    rest = ''.join(random.choices(string.digits, k=9))
    return first + rest

# ============= PASSWORD GENERATORS =============

def generate_password():
    """Generate strong random password (alphanumeric + special)"""
    length = random.randint(12, 18)
    # Include special chars in password as they're allowed
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-=<>?"
    return ''.join(random.choices(chars, k=length))

def generate_password_pattern():
    """Generate password with pattern (word+number+special)"""
    words = ["Secure", "Admin", "User", "Pass", "Login", "Access", "Root", "Power", "Master", "Prime"]
    word = random.choice(words)
    number = random.randint(100, 999)
    special = random.choice("!@#$%^&*")
    return f"{word}{number}{special}"

# ============= NAME GENERATION FUNCTIONS =============

def generate_name():
    """Generate random name (sometimes swap first/last)"""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    
    # 20% chance to swap first and last
    if random.random() < 0.2:
        first, last = last, first
    
    return first, last

# ============= ACCOUNT CREATION =============

def create_single_account(index, referral_code=None):
    """Create a single account with retry logic"""
    if not referral_code:
        referral_code = random.choice(REFERRAL_CODES)
    
    phone = generate_phone()
    password = random.choice([generate_password, generate_password_pattern])()
    android_id = ''.join(random.choices(string.hexdigits.lower(), k=16))
    fcm_token = ''.join(random.choices(string.hexdigits.lower(), k=32))
    
    first_name, last_name = generate_name()
    email = generate_unique_gmail()
    
    data = {
        "first_name": first_name,
        "last_name": last_name,
        "password": password,
        "email": email,
        "phone": phone,
        "device": android_id,
        "token": fcm_token,
        "enter_refer_code": referral_code
    }
    
    try:
        resp = requests.post(
            f"{BASE_URL}/register.php",
            data=data,
            timeout=15,
            headers={
                "User-Agent": random.choice([
                    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36",
                    "Mozilla/5.0 (Linux; Android 11; SM-G998B) AppleWebKit/537.36",
                    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36",
                    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36"
                ])
            }
        )
        
        result = resp.json()
        uid = result.get('uid')
        
        if uid and uid != 'null':
            account_data = {
                "email": email,
                "password": password,
                "phone": phone,
                "uid": uid,
                "session_id": result.get('session_id', ''),
                "referral_code": referral_code,
                "first_name": first_name,
                "last_name": last_name,
                "created_at": datetime.now().isoformat()
            }
            
            with account_lock:
                accounts.append(account_data)
                stats["successful"] += 1
                stats["accounts_created"] += 1
                stats["total_registrations"] += 1
                stats["recent_accounts"].appendleft({
                    "email": email,
                    "uid": uid,
                    "time": datetime.now().strftime("%H:%M:%S")
                })
            
            return True, account_data
        else:
            with account_lock:
                stats["failed"] += 1
                stats["total_registrations"] += 1
            return False, result.get('message', 'Unknown error')
            
    except Exception as e:
        with account_lock:
            stats["failed"] += 1
            stats["total_registrations"] += 1
        return False, str(e)

def create_batch_accounts(batch_size=100):
    """Create multiple accounts in parallel"""
    threads = []
    results = []
    
    def worker(index):
        result = create_single_account(index)
        results.append(result)
    
    for i in range(batch_size):
        thread = threading.Thread(target=worker, args=(stats["accounts_created"] + i + 1,))
        thread.daemon = True
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()
    
    return results

def continuous_creation():
    """Continuous account creation in batches"""
    while not stop_creation.is_set():
        with account_lock:
            stats["active_threads"] = len(threading.enumerate())
        
        # Create batch of 100 accounts
        batch_results = create_batch_accounts(100)
        
        # Update rate
        with rate_lock:
            request_times.append(time.time())
            if len(request_times) > 1:
                oldest = request_times[0]
                newest = request_times[-1]
                if newest - oldest > 0:
                    stats["rate"] = len(request_times) / (newest - oldest) * 60
        
        # Small delay between batches
        time.sleep(random.uniform(0.5, 1.5))

# ============= FLASK WEB INTERFACE =============

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PLAYT24 Account Creator</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0a0a0a; color: #00ff00; font-family: 'Courier New', monospace; }
        .container { max-width: 800px; margin: 50px auto; padding: 20px; background: #111; border: 1px solid #00ff00; border-radius: 10px; }
        .stat-box { background: #1a1a1a; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 3px solid #00ff00; }
        .stat-value { font-size: 2em; font-weight: bold; color: #00ff00; }
        .stat-label { color: #888; font-size: 0.9em; text-transform: uppercase; }
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
        .refresh-btn { background: #222; color: #00ff00; border: 1px solid #00ff00; padding: 5px 15px; float: right; }
        .refresh-btn:hover { background: #333; }
        .email-preview { color: #00ddff; font-size: 0.85em; }
        .badge-gmail { background: #ea4335; color: white; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
        .badge-clean { background: #34a853; color: white; font-size: 0.6em; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ PLAYT24 Account Creator
            <span class="badge-gmail">GMAIL</span>
            <span class="badge-clean">CLEAN</span>
            <button class="refresh-btn" onclick="location.reload()">⟳ Refresh</button>
        </h1>
        
        <div class="row mt-3">
            <div class="col-md-6">
                <button class="btn-control w-100" id="controlBtn" onclick="toggleCreation()">
                    {{ '⏹ Stop' if stats.status == 'running' else '▶ Start' }}
                </button>
            </div>
            <div class="col-md-6">
                <button class="btn-control w-100" style="background:#ff4444;color:#fff;" onclick="clearAccounts()">
                    🗑 Clear All
                </button>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Total Registrations</div>
                    <div class="stat-value">{{ stats.total_registrations }}</div>
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
        
        <div class="row mt-3">
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Active Threads</div>
                    <div class="stat-value">{{ stats.active_threads }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-box">
                    <div class="stat-label">Rate (accounts/min)</div>
                    <div class="stat-value">{{ "%.1f"|format(stats.rate) }}</div>
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
        
        <div class="mt-4">
            <div class="stat-box">
                <div class="stat-label">Start Time</div>
                <div>{{ stats.start_time }}</div>
            </div>
        </div>
        
        <div class="mt-4">
            <h4>Recent Accounts (last 20) <span class="badge-gmail">@gmail.com</span></h4>
            <div class="account-list">
                <table class="table table-dark table-sm">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Email</th>
                            <th>UID</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for acc in stats.recent_accounts %}
                        <tr>
                            <td>{{ acc.time }}</td>
                            <td class="email-preview">{{ acc.email }}</td>
                            <td>{{ acc.uid }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="mt-4">
            <a href="/download" class="btn btn-success btn-sm">⬇ Download Accounts ({{ stats.accounts_created }})</a>
            <a href="/stats" class="btn btn-info btn-sm">📊 JSON Stats</a>
            <span style="float:right;color:#555;font-size:0.8em;">Clean alphanumeric emails only</span>
        </div>
    </div>
    
    <script>
        function toggleCreation() {
            fetch('/toggle', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'running') {
                        document.getElementById('controlBtn').textContent = '⏹ Stop';
                        document.getElementById('controlBtn').style.background = '#ff4444';
                        document.getElementById('controlBtn').style.color = '#fff';
                    } else {
                        document.getElementById('controlBtn').textContent = '▶ Start';
                        document.getElementById('controlBtn').style.background = '#00ff00';
                        document.getElementById('controlBtn').style.color = '#000';
                    }
                    setTimeout(() => location.reload(), 1000);
                });
        }
        
        function clearAccounts() {
            if (confirm('Delete all accounts? This cannot be undone!')) {
                fetch('/clear', { method: 'POST' })
                    .then(() => location.reload());
            }
        }
        
        // Auto refresh every 10 seconds
        setTimeout(() => location.reload(), 10000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main dashboard"""
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
    """Get JSON statistics"""
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
            "uptime_seconds": (datetime.now() - datetime.fromisoformat(stats["start_time"])).total_seconds()
        }
    return jsonify(stats_copy)

@app.route('/download')
def download_accounts():
    """Download all accounts as CSV"""
    with account_lock:
        if not accounts:
            return "No accounts found", 404
        
        csv_data = "Email,Password,Phone,UID,SessionID,ReferralCode,FirstName,LastName,CreatedAt\n"
        for acc in accounts:
            csv_data += f"{acc['email']},{acc['password']},{acc['phone']},{acc['uid']},{acc['session_id']},{acc['referral_code']},{acc['first_name']},{acc['last_name']},{acc['created_at']}\n"
    
    return csv_data, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    }

@app.route('/toggle', methods=['POST'])
def toggle_creation():
    """Start/Stop account creation"""
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
    """Clear all accounts"""
    with account_lock:
        accounts.clear()
        stats["total_registrations"] = 0
        stats["successful"] = 0
        stats["failed"] = 0
        stats["accounts_created"] = 0
        stats["recent_accounts"].clear()
        used_emails.clear()
    return jsonify({"status": "cleared"})

@app.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint for Uptime Robot"""
    return jsonify({
        "status": "alive",
        "accounts": stats["accounts_created"],
        "time": datetime.now().isoformat()
    })

# ============= MAIN =============

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Start account creation automatically
    stop_creation.clear()
    stats["status"] = "running"
    stats["start_time"] = datetime.now().isoformat()
    
    creation_thread = threading.Thread(target=continuous_creation, daemon=True)
    creation_thread.start()
    
    # Run Flask app
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
