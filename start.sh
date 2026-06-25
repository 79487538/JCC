#!/bin/bash
export PYTHONUNBUFFERED=1
export ENV=production

uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2
