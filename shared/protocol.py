"""Constants shared by client and server: endpoints, headers, discovery."""

from __future__ import annotations

DEFAULT_PORT = 8765

ANALYZE_PATH = "/analyze"
HEALTH_PATH = "/health"
PAIR_PATH = "/pair"

TOKEN_HEADER = "X-Chess-Vision-Token"

# GET /health answers {"service": SERVICE_ID, ...}; the subnet scan uses it to recognise the server.
SERVICE_ID = "chess-vision"

# Body of POST /analyze is the raw encoded image; these are the accepted types.
ACCEPTED_IMAGE_TYPES = ("image/png", "image/jpeg")

MDNS_SERVICE_TYPE = "_chessvision._tcp.local."
MDNS_SERVICE_NAME = "Chess Vision"
