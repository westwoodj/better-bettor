"""Seed cache_index.json from existing depthcharts and athlete JSON files.
This is a small helper you can run from the repo root to populate the cache index
used by the ESPN client.
"""
import sys, os, json, re
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.adapters.espn_api import NFLClient

c = NFLClient()
base = c.data_dir / 'football' / 'nfl'
added = []
# depthcharts
dc_dir = base / 'depthcharts'
if dc_dir.exists():
    for p in sorted(dc_dir.glob('*.json')):
        name = p.stem
        m = re.match(r"(\d+)-(\d{4})", name)
        if m:
            team = m.group(1); year = m.group(2)
            key = f"depthchart-{team}-{year}"
            c._update_cache_index_entry(key, {'path': str(p), 'type': 'depthchart', 'team_id': team})
            added.append(key)
# athletes
at_dir = base / 'athletes'
if at_dir.exists():
    for p in sorted(at_dir.glob('*.json')):
        name = p.stem
        aid = name.split('-')[0]
        key = f"athlete-{aid}"
        c._update_cache_index_entry(key, {'path': str(p), 'type': 'athlete', 'athlete_id': aid})
        added.append(key)

print(json.dumps({'added': added}, indent=2))

