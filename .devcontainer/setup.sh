#!/usr/bin/env bash
set -euo pipefail

cd /app
exec bash scripts/dev setup --browser
