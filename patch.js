const fs = require('fs');
const file = '/Users/scott/GitHub/subwave/controller/src/llm/internal/provider/registry.ts';
let code = fs.readFileSync(file, 'utf8');

const target1 = `                          if (props && (props.text || props.say || props.reason || props.query)) {
                            const synthArgs: Record<string, any> = {};
                            if (props.id)     synthArgs.id     = \`synth-\${Date.now()}\`;
                            if (props.reason) synthArgs.reason = 'auto';
                            if (props.air)    synthArgs.air    = true;
                            if (props.say)    synthArgs.say    = raw;
                            if (props.text)   synthArgs.text   = raw;
                            if (props.transition) synthArgs.transition = 'auto';
                            if (props.sfx)    synthArgs.sfx    = null;
                            if (props.query)  synthArgs.query  = raw;`;

const replacement1 = `                          if (props && (props.text || props.say || props.reason || props.query || props.ack || props.kind)) {
                            const synthArgs: Record<string, any> = {};
                            if (props.id)     synthArgs.id     = \`synth-\${Date.now()}\`;
                            if (props.reason) synthArgs.reason = 'auto';
                            if (props.air)    synthArgs.air    = true;
                            if (props.say)    synthArgs.say    = raw;
                            if (props.text)   synthArgs.text   = raw;
                            if (props.ack)    synthArgs.ack    = raw;
                            if (props.kind)   synthArgs.kind   = 'track';
                            if (props.transition) synthArgs.transition = 'auto';
                            if (props.sfx)    synthArgs.sfx    = null;
                            if (props.query)  synthArgs.query  = raw;`;

code = code.replace(target1, replacement1);

const target2 = `                      const synthArgs: Record<string, any> = {};
                      if (props.id)     synthArgs.id     = parsedFromContent?.id ?? \`synth-\${Date.now()}\`;
                      if (props.reason) synthArgs.reason = parsedFromContent?.reason ?? 'auto';
                      if (props.air)    synthArgs.air    = parsedFromContent?.air ?? true;
                      if (props.say)    synthArgs.say    = parsedFromContent?.say ?? content;
                      if (props.text)   synthArgs.text   = parsedFromContent?.text ?? (parsedFromContent?.parameters?.text ?? content);
                      if (props.transition) synthArgs.transition = parsedFromContent?.transition ?? 'auto';
                      if (props.sfx)    synthArgs.sfx    = parsedFromContent?.sfx ?? null;`;

const replacement2 = `                      const synthArgs: Record<string, any> = parsedFromContent ? { ...parsedFromContent } : {};
                      if (!parsedFromContent) {
                        if (props.id)     synthArgs.id     = \`synth-\${Date.now()}\`;
                        if (props.reason) synthArgs.reason = 'auto';
                        if (props.air)    synthArgs.air    = true;
                        if (props.say)    synthArgs.say    = content;
                        if (props.text)   synthArgs.text   = content;
                        if (props.ack)    synthArgs.ack    = content;
                        if (props.kind)   synthArgs.kind   = 'track';
                        if (props.transition) synthArgs.transition = 'auto';
                        if (props.sfx)    synthArgs.sfx    = null;
                        if (props.query)  synthArgs.query  = content;
                      }`;

code = code.replace(target2, replacement2);

fs.writeFileSync(file, code);
console.log('Patched registry.ts');
