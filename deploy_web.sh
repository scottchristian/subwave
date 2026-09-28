#!/bin/bash
set -e
cd web
npm ci
npm run build
# See deploy_controller.sh: keep macOS AppleDouble files out of the tarball.
COPYFILE_DISABLE=1 tar -czf update.tar.gz .next/standalone .next/static
scp update.tar.gz root@192.168.68.196:/root/subwave/
ssh root@192.168.68.196 'cd /root/subwave && rm -rf extracted && mkdir -p extracted && tar -xzf update.tar.gz -C extracted/ && docker exec -u 0 sub-wave-web rm -rf /app/.next && docker exec -u 0 sub-wave-web mkdir -p /app/.next && docker cp extracted/.next/standalone/. sub-wave-web:/app/ && docker cp extracted/.next/static sub-wave-web:/app/.next/ && docker compose restart web'
echo "Deployed successfully!"
