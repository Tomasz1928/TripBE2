#!/usr/bin/env bash
# build.sh — Render runs this during every deploy

set -o errexit  # exit on error

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Collecting static files..."
python mainProject/manage.py collectstatic --no-input

echo "==> Running database migrations..."
python mainProject/manage.py migrate --no-input

echo "==> Build complete!"