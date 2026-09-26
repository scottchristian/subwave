const fs = require('fs');
const settings = JSON.parse(fs.readFileSync('scratch_settings.json', 'utf8'));

// Fix LLM
settings.llm.provider = "openai-compatible";
settings.llm.model = "Free_Shit";
settings.llm.baseUrl = "http://192.168.68.193:20128/v1";
settings.llm.apiKey = "sk-e9e3d448418a71bf-1kwgtp-466aefc7"; // From GEMINI_API_KEY
settings.llm.fallback.enabled = true;
settings.llm.fallback.provider = "google";
settings.llm.fallback.model = "gemini-2.5-flash";

// Fix Skills
settings.skills.enabled = {
  "pulse-tasmania-news": true,
  "news": false,
  "midway-tavern": true,
  "listener-shoutout": true,
  "midway-social-club": true,
  "station-stats": true,
  "album-anniversary": false,
  "curiosity": false,
  "library-deep-cut": false,
  "thirsty-camel": true,
  "grog-finder": true,
  "story-gay-lifestyle": true,
  "supporter-shoutout": true,
  "sports-odds": true,
  "waze-alerts": true,
  "upcoming-shows": true,
  "bmac-shoutout": true
};

fs.writeFileSync('scratch_settings_fixed.json', JSON.stringify(settings, null, 2));
