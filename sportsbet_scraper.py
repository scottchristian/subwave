import sqlite3
import requests
import json
import time

DB_PATH = "/root/subwave/state/sports_odds.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS odds (
            id TEXT PRIMARY KEY,
            sport TEXT,
            participant1 TEXT,
            participant2 TEXT,
            odds1 REAL,
            odds2 REAL,
            start_time INTEGER,
            updated_at INTEGER
        )
    ''')
    conn.commit()
    return conn

def fetch_top_matches(conn, sport, comp_id, limit=3):
    print(f"Fetching {sport} matches (Comp ID {comp_id})...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(
            f"https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/{comp_id}?page=1&size=50",
            headers=headers
        )
        if resp.status_code != 200:
            print(f"Error fetching {sport}: {resp.status_code}")
            return
            
        data = resp.json()
        events = data.get("events", [])
        
        # Filter for MTCH (Match) events and sort by start time
        matches = [e for e in events if e.get("eventSort") == "MTCH"]
        matches.sort(key=lambda x: x.get("startTime", 0))
        
        top_matches = matches[:limit]
        
        c = conn.cursor()
        
        # Clear out old odds for this sport before we insert new ones so we only keep upcoming
        c.execute("DELETE FROM odds WHERE sport = ?", (sport,))
        
        for match in top_matches:
            event_id = match["id"]
            p1 = match.get("participant1")
            p2 = match.get("participant2")
            start_time = match.get("startTime")
            
            # Fetch the actual odds for this match
            event_resp = requests.get(
                f"https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports/Events/{event_id}",
                headers=headers
            )
            if event_resp.status_code != 200:
                continue
                
            event_data = event_resp.json()
            market_list = event_data.get("marketList", [])
            if not market_list:
                continue
                
            # Usually the first market is Head to Head, but let's be safe
            h2h_market = next((m for m in market_list if m.get("name") in ["Head to Head", "Match Betting"]), None)
            if not h2h_market:
                continue
                
            selections = h2h_market.get("selections", [])
            if len(selections) != 2:
                continue
                
            odds1 = None
            odds2 = None
            
            for sel in selections:
                price = sel.get("price", {}).get("winPrice")
                name = sel.get("name")
                
                # Try to map prices to participant 1 or 2
                if name == p1:
                    odds1 = price
                elif name == p2:
                    odds2 = price
                
                # Fallback if participant names don't exactly match selection names
                if odds1 is None and name != p2:
                    odds1 = price
                elif odds2 is None and name != p1:
                    odds2 = price

            if odds1 is not None and odds2 is not None:
                c.execute('''
                    INSERT INTO odds (id, sport, participant1, participant2, odds1, odds2, start_time, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (str(event_id), sport, p1, p2, odds1, odds2, start_time, int(time.time())))
                print(f"Saved {sport} match: {p1} (${odds1}) vs {p2} (${odds2})")
                
        conn.commit()

    except Exception as e:
        print(f"Exception fetching {sport}: {e}")

def main():
    conn = init_db()
    fetch_top_matches(conn, "AFL", 4165, limit=2)
    time.sleep(1) # Be nice to API
    fetch_top_matches(conn, "UFC", 3703, limit=2)
    conn.close()
    print("Scraping complete.")

if __name__ == "__main__":
    main()
