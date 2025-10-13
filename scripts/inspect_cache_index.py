"""Inspect cache_index.json and print a short summary (count and first 10 entries with age and freshness).
"""
import sys, os, time, json
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.adapters.espn_api import NFLClient

c = NFLClient()
idx = c._load_cache_index()
now = int(time.time())
print(json.dumps({'count': len(idx)}, indent=2))

i = 0
for k, v in idx.items():
    if i >= 10:
        break
    ts = v.get('timestamp', 0)
    age = now - int(ts)
    fresh = c._is_cache_fresh(k)
    print(json.dumps({'key': k, 'path': v.get('path'), 'type': v.get('type'), 'age_seconds': age, 'fresh': fresh}, indent=2))
    i += 1

# show default TTL
print('\nDefault cache TTL seconds:', c.cache_ttl_seconds)

