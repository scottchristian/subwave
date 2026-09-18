import requests
url = "http://192.168.68.193:20128/v1/chat/completions"
headers = {
    "Authorization": "Bearer sk-e9e3d448418a71bf-1kwgtp-466aefc7",
    "Content-Type": "application/json"
}
payload = {
    "model": "free_shit",
    "messages": [{"role": "user", "content": "Say hello using the emit tool."}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "emit",
            "description": "emit a greeting",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}}
            }
        }
    }],
    "tool_choice": "required",
    "stream": False
}
r = requests.post(url, headers=headers, json=payload)
print(r.status_code)
print(r.text)
