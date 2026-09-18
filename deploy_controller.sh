#!/bin/bash
set -e
echo "Copying to server..."
scp controller/src/settings/defaults.ts root@192.168.68.196:/root/subwave/defaults.ts
scp controller/src/settings.ts root@192.168.68.196:/root/subwave/settings.ts
scp controller/src/llm/internal/provider/registry.ts root@192.168.68.196:/root/subwave/registry.ts
scp controller/src/audio/remoteTts.ts root@192.168.68.196:/root/subwave/remoteTts.ts
scp gemini_tts.py root@192.168.68.196:/root/subwave/gemini-tts/gemini_tts.py

echo "Patching containers..."
ssh root@192.168.68.196 'cd /root/subwave && \
docker cp defaults.ts sub-wave-controller:/app/src/settings/defaults.ts && \
docker cp settings.ts sub-wave-controller:/app/src/settings.ts && \
docker cp registry.ts sub-wave-controller:/app/src/llm/internal/provider/registry.ts && \
docker cp remoteTts.ts sub-wave-controller:/app/src/audio/remoteTts.ts && \
docker compose restart controller'
echo "Deployed controller successfully!"
