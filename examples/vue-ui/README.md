Vue 3 demo UI — NFL Game Analysis

Quickstart

1. From the repository root run a simple HTTP server so browsers can fetch the JSON file:
   - Using Python (works if Python is installed):
     python -m http.server 8000

2. Open the demo in your browser:
   http://localhost:8000/examples/vue-ui/index.html

Notes

- The UI expects the `all-teams.json` file at `/src/nfl_data_aggregator/data/espn/football/nfl/all-teams.json` relative to the server root (this matches the repo layout).
- Type into the Home/Away fields to filter teams by name, abbreviation, or location; click a suggestion to select.
- Select bet type filters and click "Run analysis" to prepare the payload (displayed on the page).
- For production use, replace the demo payload display in `app.js` with a call to your analysis backend or local logic.

POSTing to a test endpoint

This UI can POST the prepared payload to a test endpoint (default: `https://httpbin.org/post`). Toggle the "Send" checkbox to enable posting.

Important: CORS

- Browsers enforce Cross-Origin Resource Sharing (CORS). If you set the endpoint to a server you control, ensure that server returns the appropriate CORS headers (for example `Access-Control-Allow-Origin: *` for public testing) so the browser will allow the POST.
- If the endpoint does not enable CORS, the browser will block the request and you'll see a CORS-related error in the console — the UI will display the error text if the fetch fails.

Example request payload (JSON)

This is the exact compact payload the UI will POST when "Send" is enabled:

```json
{
  "home": { "id": "22", "name": "Arizona Cardinals", "abbreviation": "ARI" },
  "away": { "id": "1", "name": "Atlanta Falcons", "abbreviation": "ATL" },
  "betTypes": [ "spread", "total" ],
  "timestamp": "2025-10-13T12:34:56.789Z"
}
```

Example response (httpbin.org)

When posting to `https://httpbin.org/post`, the service echoes back the request. The UI will try to parse JSON responses; if the response is text it will be shown as raw text.

Example curl command (useful to test server behavior / CORS from server-side):

```bash
curl -X POST https://httpbin.org/post \
  -H "Content-Type: application/json" \
  -d '{"home":{"id":"22","name":"Arizona Cardinals","abbreviation":"ARI"},"away":{"id":"1","name":"Atlanta Falcons","abbreviation":"ATL"},"betTypes":["spread"],"timestamp":"2025-10-13T12:34:56Z"}'
```

Example fetch (browser) — same shape as the UI uses:

```javascript
fetch('https://httpbin.org/post', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload)
}).then(r => r.json()).then(console.log).catch(console.error);
```

If you want me to wire the UI to a local test endpoint in this repo (for example a tiny Flask or Node endpoint to receive and return the payload with proper CORS headers), I can add that server and instructions.
