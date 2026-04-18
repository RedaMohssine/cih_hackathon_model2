#!/bin/bash
set -e
SITE=$(pip show uvicorn | grep Location | awk '{print $2}')
BIN=$(echo $SITE | sed 's|/lib/python[0-9.]*/site-packages||')/bin
exec $BIN/uvicorn main:app --host 0.0.0.0 --port $PORT
