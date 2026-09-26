const fs = require('fs');
const settings = JSON.parse(fs.readFileSync('scratch_settings_fixed.json', 'utf8'));
settings.llm.debugRawRequests = true;
fs.writeFileSync('scratch_settings_fixed.json', JSON.stringify(settings, null, 2));
