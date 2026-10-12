import requests
import json

r = requests.post('http://localhost:8000/api/geocode', json={'address': 'Hanuman mandir ke piche ration shop ke pas 2nd gali', 'language': 'hi'})
print(f"Status: {r.status_code}")
print(f"Response: {json.dumps(r.json(), indent=2)}")