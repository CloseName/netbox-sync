#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]]
cd /netbox/containers
# Keep all observed data and the final report; stop the scheduled renderer first.
rm -f /etc/cron.d/netbox-usage-report
rm -f /netbox/containers/configuration/zz_usage.py
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.images.yml -f docker-compose.guard.yml up -d --no-deps --pull never --force-recreate --wait --wait-timeout 300 netbox netbox-worker
flock -w 60 /run/netbox-usage-report.lock python3 /netbox/usage-collector/report.py --directory /netbox/usage-data
rm -f /netbox/containers/docker-compose.usage.yml
rm -f /netbox/usage-collector/netbox_usage/__init__.py /netbox/usage-collector/netbox_usage/middleware.py /netbox/usage-collector/report.py
rm -f /netbox/usage-collector/uninstall.sh
echo 'Collector disabled and removed. Historical data: /netbox/usage-data'
