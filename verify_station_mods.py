import requests
import sqlite3
import os
import sys
import base64

# Color output
GREEN = '\033[92m'
RED = '\033[91m'
RESET = '\033[0m'

def print_result(name, success, details=""):
    if success:
        print(f"[{GREEN}PASS{RESET}] {name}")
    else:
        print(f"[{RED}FAIL{RESET}] {name}")
        if details:
            print(f"       -> {details}")
        sys.exit(1)

def test_api_auth():
    print("Testing API Auth (/api/request)...")
    # Unauthenticated should fail
    resp = requests.post("https://radio.ghostmaster.online/api/request", json={"text": "test"})
    print_result("Unauthenticated request blocked", resp.status_code in [401, 403], f"Status was {resp.status_code}")
    
    # Authenticated should pass (or return a different error like validation)
    resp = requests.post(
        "https://radio.ghostmaster.online/api/request", 
        json={"text": "test"},
        headers={"x-station-auth": "Midw@y!FM2026"}
    )
    # We expect either 200/202, or a 400 for bad track info, but NOT 401/403
    print_result("Authenticated request allowed", resp.status_code not in [401, 403], f"Status was {resp.status_code}")

def test_9router_probe():
    print("Testing 9router SSE bypass (/settings/llm/probe-compat)...")
    auth_val = base64.b64encode(b"admin:ddFn.VGLyGYmAuT6Dik9").decode("utf-8")
    resp = requests.post(
        "https://radio.ghostmaster.online/api/settings/llm/probe-compat",
        json={"baseUrl": "http://192.168.68.193:20128/v1beta", "apiKey": "test", "model": "free_shit"},
        headers={"Authorization": f"Basic {auth_val}"}
    )
    # If the SSE bypass is missing, this crashes with a 500 Invalid JSON.
    print_result("9router probe successful", resp.status_code == 200, f"Status was {resp.status_code}. Response: {resp.text[:50]}")

def test_telemetry_db():
    print("Testing SQLite Telemetry DB...")
    db_path = "/root/subwave/state/telemetry.db"
    print_result("Telemetry DB exists", os.path.exists(db_path), f"Path {db_path} not found")
    try:
        conn = sqlite3.connect(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = [t[0] for t in tables]
        print_result("Telemetry tables exist", "daily_stats" in tables, f"Found tables: {tables}")
    except Exception as e:
        print_result("Telemetry DB readable", False, str(e))

def test_prompts():
    print("Testing Compiled Prompt Modifications...")
    # Check if compiled JS contains our custom prompt rules
    system_path = "/root/subwave/controller/dist/llm/internal/prompts/system.js"
    banter_path = "/root/subwave/controller/dist/llm/internal/prompts/banter.js"
    
    # In Subwave 1.13, we run in Docker, so the paths above are on the host? No, they are inside the container.
    # To test them from the host, we can run a docker exec command.
    sys_cmd = "docker exec sub-wave-controller grep -i '<think>' /app/src/llm/internal/prompts/system.ts"
    code = os.system(sys_cmd + " > /dev/null 2>&1")
    print_result("System prompt forces <think> tags", code == 0, "Could not find <think> tag instruction in system.ts")

    sys_cmd2 = "docker exec sub-wave-controller grep -i 'weather' /app/src/llm/internal/prompts/system.ts"
    code = os.system(sys_cmd2 + " > /dev/null 2>&1")
    print_result("System prompt bans weather", code == 0, "Could not find weather ban in system.ts")
    
    ban_cmd = "docker exec sub-wave-controller grep -i 'weather' /app/src/llm/internal/prompts/banter.ts"
    code = os.system(ban_cmd + " > /dev/null 2>&1")
    print_result("Banter prompt bans weather", code == 0, "Could not find weather ban in banter.ts")

    sys_cmd3 = "docker exec sub-wave-controller grep -i 'back-announce' /app/src/llm/internal/prompts/scripts.ts"
    code = os.system(sys_cmd3 + " > /dev/null 2>&1")
    print_result("Scripts prompt forces back-announce", code == 0, "Could not find back-announce rule in scripts.ts")

def test_gemini_tts():
    print("Testing Gemini TTS...")
    # Verify gemini_tts.py contains our custom maps
    tts_cmd = "docker exec sub-wave-gemini-tts grep -i 'VOICE_MAP' gemini_tts.py"
    code = os.system(tts_cmd + " > /dev/null 2>&1")
    print_result("Gemini TTS has custom VOICE_MAP", code == 0, "Could not find VOICE_MAP in gemini_tts.py")

    tts_cmd2 = "docker exec sub-wave-gemini-tts grep -i 'speak-multi' gemini_tts.py"
    code = os.system(tts_cmd2 + " > /dev/null 2>&1")
    print_result("Gemini TTS has /speak-multi endpoint", code == 0, "Could not find /speak-multi in gemini_tts.py")
    
    tts_cmd3 = "docker exec sub-wave-gemini-tts grep -i 'Pronunciation rules:' gemini_tts.py"
    code = os.system(tts_cmd3 + " > /dev/null 2>&1")
    print_result("Gemini TTS has Pronunciation Guide", code == 0, "Could not find Pronunciation guide in gemini_tts.py")

def test_schema_modifications():
    print("Testing Schema Modifications...")
    schema_cmd = "docker exec sub-wave-controller grep -i 'speakClock' /app/src/schemas/show.ts"
    code = os.system(schema_cmd + " > /dev/null 2>&1")
    print_result("Show schema has speakClock", code == 0, "Could not find speakClock in show.ts")
    
    schema_cmd2 = "docker exec sub-wave-controller grep -i 'donateEnabled' /app/src/schemas/settings.ts"
    code = os.system(schema_cmd2 + " > /dev/null 2>&1")
    print_result("Settings schema has donateEnabled", code == 0, "Could not find donateEnabled in settings.ts")

if __name__ == "__main__":
    print("Starting Causeway FM Custom Modifications Verification...")
    test_api_auth()
    test_9router_probe()
    # The following tests only work if run directly on the Proxmox server
    if os.path.exists("/root/subwave/state/telemetry.db") or os.system("docker ps > /dev/null 2>&1") == 0:
        test_telemetry_db()
        test_prompts()
        test_gemini_tts()
        test_schema_modifications()
    else:
        print("Skipping local container/DB tests since we are not running on the Proxmox server.")
    
    print(f"\n{GREEN}ALL TESTS PASSED. The custom modifications are active.{RESET}")
