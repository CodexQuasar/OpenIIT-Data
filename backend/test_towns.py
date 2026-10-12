import urllib.request
import json

try:
    url = 'http://localhost:8000/api/real/towns'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as response:
        print('Status:', response.status)
        data = response.read().decode('utf-8')
        print('Response:', data[:500])
except Exception as e:
    print('Error:', e)