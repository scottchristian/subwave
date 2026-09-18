#!/usr/bin/env python3
import requests
import json
import sqlite3
import datetime
import os
import re

DB_PATH = '/root/subwave/state/bottle_shops.db'

# Define items and their specific store lookup data
ITEMS = {
    'xxxx-30': {
        'name': 'XXXX Gold 30 Block',
        'thirsty_camel_url': 'https://www.thirstycamel.com.au/product/xxxx-gold-lager-can-375ml-30-pack/e63b646cb4',
        'bws_id': '993087',
        'liquorland_id': None
    },
    'carlton-dry-30': {
        'name': 'Carlton Dry 30 Block',
        'thirsty_camel_url': 'https://www.thirstycamel.com.au/product/carlton-dry-3-5-percent-can-375ml--30-pack/02a19fb865',
        'bws_id': '311856',
        'liquorland_id': '7023591_pack30'
    },
    'carlton-dry-24': {
        'name': 'Carlton Dry 24 Pack',
        'thirsty_camel_url': None,
        'bws_id': '311856',
        'liquorland_id': None
    },
    'jim-beam-700': {
        'name': 'Jim Beam 700ml',
        'thirsty_camel_url': 'https://www.thirstycamel.com.au/product/jim-beam-white-label-bourbon-700ml/4027f6f441',
        'bws_id': '90248',
        'liquorland_id': None
    },
    'jim-beam-1l': {
        'name': 'Jim Beam 1L',
        'thirsty_camel_url': 'https://www.thirstycamel.com.au/product/jim-beam-white-label-bourbon-1l/f525e1fac8',
        'bws_id': '335009',
        'liquorland_id': None
    },
    'cascade-lager-24': {
        'name': 'Cascade Lager 24 Pack',
        'thirsty_camel_url': 'https://www.thirstycamel.com.au/product/cascade-lager-can-375ml-24-pack/b6efa950f4',
        'bws_id': '116916',
        'liquorland_id': None
    }
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            store_id TEXT CHECK(store_id IN ('thirsty_camel', 'bws', 'dan_murphys', 'liquorland')),
            item_id TEXT,
            current_price REAL,
            max_price REAL,
            updated_at TEXT,
            PRIMARY KEY (store_id, item_id)
        )
    ''')
    
    # Create the view for the LLM to use
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS cheapest_prices AS 
        SELECT item_id, MIN(current_price) as best_price, store_id 
        FROM prices 
        GROUP BY item_id;
    ''')
    
    conn.commit()
    return conn

def get_thirsty_camel_price(url):
    if not url: return None
    cookies = {'selected_store': 'midway-point-tavern'}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, cookies=cookies, headers=headers, timeout=10)
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
        if not match: return None
        data = json.loads(match.group(1))
        prices = []
        def find_store_pricing(obj):
            if isinstance(obj, dict):
                if 'price' in obj and isinstance(obj['price'], (int, float)) and obj.get('type') in ['STORE', 'PRICELIST', 'PROMOTION', 'SPECIAL']:
                    prices.append(float(obj['price']) / 100.0)
                for v in obj.values(): find_store_pricing(v)
            elif isinstance(obj, list):
                for item in obj: find_store_pricing(item)
        find_store_pricing(data)
        if prices: return min(prices)
    except Exception as e:
        print(f"Error fetching Thirsty Camel: {e}")
    return None

def get_bws_price(bws_id):
    if not bws_id: return None
    
    url = f"https://api.bws.com.au/apis/ui/Product/{bws_id}"
    
    # Use the exact headers provided by the user's curl to bypass Cloudflare
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
        'origin': 'https://bws.com.au',
        'priority': 'u=1, i',
        'referer': 'https://bws.com.au/',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36'
    }
    
    # Ensure the Sorell Drive store cookie is included (Store ID might be encoded in the cookie, specifically 's-2763713')
    cookies = {
        'w-lrkswrdjp': 'dm-Pickup,f-7025,s-2763713'
    }
    
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if r.status_code == 200:
            data = r.json()
            products = data.get('Products', [])
            prices = []
            for p in products:
                if 'Price' in p:
                    prices.append(float(p['Price']))
            if prices:
                return max(prices)
    except Exception as e:
        print(f"Error fetching BWS: {e}")
    return None

def get_liquorland_price(ll_id):
    if not ll_id: return None
    import subprocess
    url = f"https://www.liquorland.com.au/api/products/ll/tas/beer-and-cider/{ll_id}?catalogue=1&v=2&storeId=5916"
    cmd = [
        "curl", "-s", "--url", url,
        "-b", "__uzma=29f8caa2-795f-4b26-a4ae-6fc4dfe60c31; __uzmb=1789003502; __uzmc=380866765421; __uzmd=1789003535",
        "-H", 'sec-ch-ua-platform: "macOS"',
        "-H", 'ai-score-cluster;',
        "-H", 'Referer: https://www.liquorland.com.au/',
        "-H", 'sec-ch-ua: "Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
        "-H", 'sec-ch-ua-mobile: ?0',
        "-H", 'client-id: GA1.1.1282880086.1789003505',
        "-H", 'user-id: {593bd17b-a5e3-44ac-8f37-21fffc74cd13}',
        "-H", 'Accept: application/json, text/plain, */*',
        "-H", 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if 'product' in data and 'price' in data['product'] and 'current' in data['product']['price']:
                return float(data['product']['price']['current'])
    except Exception as e:
        print(f"Error fetching Liquorland via curl: {e}")
    return None

def update_price(conn, store_id, item_id, price):
    cursor = conn.cursor()
    cursor.execute('SELECT max_price FROM prices WHERE store_id = ? AND item_id = ?', (store_id, item_id))
    row = cursor.fetchone()
    
    now = datetime.datetime.now().isoformat()
    
    if row is None:
        cursor.execute('''
            INSERT INTO prices (store_id, item_id, current_price, max_price, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (store_id, item_id, price, price, now))
        print(f"[{store_id}] [{item_id}] Initialized at ${price:.2f}")
    else:
        max_price = row[0]
        if price > max_price:
            max_price = price
            
        cursor.execute('''
            UPDATE prices 
            SET current_price = ?, max_price = ?, updated_at = ?
            WHERE store_id = ? AND item_id = ?
        ''', (price, max_price, now, store_id, item_id))
        
        if price < max_price:
            print(f"[{store_id}] [{item_id}] ON SPECIAL! ${price:.2f} (Max: ${max_price:.2f})")
        else:
            print(f"[{store_id}] [{item_id}] Updated at ${price:.2f} (Max: ${max_price:.2f})")
            
    conn.commit()

def main():
    conn = init_db()
    for item_id, info in ITEMS.items():
        # Thirsty Camel
        tc_price = get_thirsty_camel_price(info.get('thirsty_camel_url'))
        if tc_price is not None:
            update_price(conn, 'thirsty_camel', item_id, tc_price)
            
        # BWS
        bws_price = get_bws_price(info.get('bws_id'))
        if bws_price is not None:
            update_price(conn, 'bws', item_id, bws_price)
        
        # Liquorland (Disabled due to ShieldSquare IP blocking)
        # ll_price = get_liquorland_price(info.get('liquorland_id'))
        # if ll_price is not None:
        #     update_price(conn, 'liquorland', item_id, ll_price)
            
    conn.close()

if __name__ == '__main__':
    main()
