#!/bin/bash
set -e
echo "Copying to server..."
# COPYFILE_DISABLE=1 keeps macOS AppleDouble (._*) files out of the tarball —
# a stray ._pick-criteria.md once crash-looped the controller on boot.
COPYFILE_DISABLE=1 tar -czf update.tar.gz controller/src gemini_tts.py
scp update.tar.gz root@192.168.68.196:/root/subwave/update.tar.gz

echo "Patching containers..."
ssh root@192.168.68.196 'cd /root/subwave && \
tar -xzf update.tar.gz && \
docker cp controller/src sub-wave-controller:/app/ && \
cp gemini_tts.py gemini-tts/gemini_tts.py && \
docker compose restart controller'
echo "Deployed controller successfully!"
