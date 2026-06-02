import requests, json

headers = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": "https://divar.ir",
    "referer": "https://divar.ir/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "x-render-type": "CSR",
    "x-standard-divar-error": "true",
}

cookies = {
    "did": "17ce261b-26bf-41cd-a27b-d3bf422c8b78",
    "city": "tehran",
}

# Use the token from the listing we just got
token = "gaAMobkx"

r = requests.get(
    f"https://api.divar.ir/v8/posts-v2/web/{token}",
    headers=headers,
    cookies=cookies,
)

print(r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:6000])