import logging
logger = logging.getLogger(__name__)

# ok: logger-fstring — %s style
logger.info("Processing series %s", series_id)

# ok: logger-fstring — static string
logger.error("Connection failed")

# ok: logger-fstring — f-string in print, not logger
print(f"Debug: {value}")
