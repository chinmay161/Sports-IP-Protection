#!/bin/sh
sleep 5
mc alias set local http://minio:9000 minioadmin minioadmin
mc mb --ignore-existing local/sports-ip-live
mc mb --ignore-existing local/sports-ip-evidence
mc mb --ignore-existing local/sports-ip-thumbnails
mc anonymous set download local/sports-ip-thumbnails
echo "MinIO buckets initialised"
