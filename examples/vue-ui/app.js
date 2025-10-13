// Simple Vue 3 app for selecting teams and running a demo analysis
const { createApp } = Vue;

const app = createApp({
  data() {
    return {
      teams: [],
      searchHome: '',
      searchAway: '',
      selectedHome: null,
      selectedAway: null,
      showHomeSuggestions: false,
      showAwaySuggestions: false,
      betTypes: [
        { label: 'Spread', value: 'spread' },
        { label: 'Moneyline', value: 'moneyline' },
        { label: 'Totals (Over/Under)', value: 'total' },
        { label: 'Prop Bets', value: 'prop' }
      ],
      selectedBetTypes: [],
      analysisResult: null,
      loading: false,
      error: null,
      // endpoint and sending state
      endpointUrl: 'https://httpbin.org/post',
      sendToEndpoint: false,
      // request/response tracking
      requestPayload: null,
      serverResponse: null,
      serverError: null
    };
  },
  computed: {
    filteredHome() {
      const q = (this.searchHome || '').trim().toLowerCase();
      if (!q) return this.teams;
      return this.teams.filter(t => {
        return (
          (t.displayName && t.displayName.toLowerCase().includes(q)) ||
          (t.abbreviation && t.abbreviation.toLowerCase().includes(q)) ||
          (t.location && t.location.toLowerCase().includes(q))
        );
      });
    },
    filteredAway() {
      const q = (this.searchAway || '').trim().toLowerCase();
      if (!q) return this.teams;
      return this.teams.filter(t => {
        return (
          (t.displayName && t.displayName.toLowerCase().includes(q)) ||
          (t.abbreviation && t.abbreviation.toLowerCase().includes(q)) ||
          (t.location && t.location.toLowerCase().includes(q))
        );
      });
    },
    prettyRequest() {
      try {
        return JSON.stringify(this.requestPayload, null, 2);
      } catch (e) {
        return String(this.requestPayload);
      }
    },
    prettyResponse() {
      try {
        return JSON.stringify(this.serverResponse, null, 2);
      } catch (e) {
        return String(this.serverResponse);
      }
    }
  },
  methods: {
    async loadTeams() {
      this.loading = true;
      this.error = null;
      try {
        // Path assumes you serve the repo root. Adjust if you host files differently.
        const res = await fetch('/src/nfl_data_aggregator/data/espn/football/nfl/all-teams.json');
        if (!res.ok) {
          this.error = 'Failed to load teams JSON: ' + res.status;
          return;
        }
        const json = await res.json();
        // Navigate the ESPN JSON structure to extract team objects
        const sports = json.sports || [];
        let teamsArr = [];
        for (const sp of sports) {
          if (!sp.leagues) continue;
          for (const lg of sp.leagues) {
            if (!lg.teams) continue;
            for (const twrap of lg.teams) {
              const t = twrap.team;
              if (!t) continue;
              // prefer scoreboard logo if available
              let logoHref = null;
              if (Array.isArray(t.logos)) {
                // try to find a scoreboard rel variant
                const scoreboard = t.logos.find(l => Array.isArray(l.rel) && l.rel.includes('scoreboard'));
                logoHref = (scoreboard && scoreboard.href) || (t.logos[0] && t.logos[0].href) || null;
              }
              teamsArr.push({
                id: t.id || t.uid || t.slug || t.displayName,
                displayName: t.displayName || t.name || t.shortDisplayName,
                abbreviation: t.abbreviation || '',
                location: t.location || '',
                href: logoHref
              });
            }
          }
        }
        // Sort alphabetically
        teamsArr.sort((a,b) => a.displayName.localeCompare(b.displayName));
        this.teams = teamsArr;
      } catch (err) {
        console.error(err);
        this.error = err.message || String(err);
      } finally {
        this.loading = false;
      }
    },
    selectHome(t) {
      this.selectedHome = t;
      this.searchHome = t.displayName;
      this.showHomeSuggestions = false;
    },
    selectAway(t) {
      this.selectedAway = t;
      this.searchAway = t.displayName;
      this.showAwaySuggestions = false;
    },
    onHomeBlur() {
      // small timeout to allow click selection
      setTimeout(() => { this.showHomeSuggestions = false; }, 150);
    },
    onAwayBlur() {
      setTimeout(() => { this.showAwaySuggestions = false; }, 150);
    },
    runAnalysis() {
      // Validate
      const result = { error: null };
      if (!this.selectedHome || !this.selectedAway) {
        result.error = 'Please select both home and away teams.';
        this.analysisResult = result;
        return;
      }
      if (this.selectedHome.id === this.selectedAway.id) {
        result.error = 'Home and away teams must be different.';
        this.analysisResult = result;
        return;
      }

      // Prepare and show payload (in real app you'd call your backend here)
      this.analysisResult = {
        home: this.selectedHome,
        away: this.selectedAway,
        betTypes: this.selectedBetTypes
      };

      // Build a compact request payload to send to endpoints (IDs + display names + bet types)
      const payload = {
        home: { id: this.selectedHome.id, name: this.selectedHome.displayName, abbreviation: this.selectedHome.abbreviation },
        away: { id: this.selectedAway.id, name: this.selectedAway.displayName, abbreviation: this.selectedAway.abbreviation },
        betTypes: this.selectedBetTypes,
        timestamp: new Date().toISOString()
      };

      // Expose the outgoing request payload in the UI
      this.requestPayload = payload;
      this.serverResponse = null;
      this.serverError = null;

      // If the user toggled "Send", POST the payload to the configured endpoint
      if (this.sendToEndpoint && this.endpointUrl) {
        // Note: CORS must be enabled on the target endpoint for browsers to allow this request.
        fetch(this.endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(async (res) => {
          const text = await res.text();
          // Try parse as JSON
          try {
            this.serverResponse = JSON.parse(text);
          } catch (e) {
            // if not JSON, store raw text
            this.serverResponse = { status: res.status, text };
          }
          if (!res.ok) {
            this.serverError = `Server returned ${res.status}`;
          }
        }).catch(err => {
          console.error('POST error', err);
          this.serverError = err.message || String(err);
        });
      }
    }
  },
  mounted() {
    this.loadTeams();
  }
});

// mount once and keep the instance if needed
const vm = app.mount('#app');
