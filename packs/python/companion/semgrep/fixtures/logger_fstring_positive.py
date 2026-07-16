import logging
logger = logging.getLogger(__name__)

# ruleid: logger-fstring
logger.info(f"Processing series {series_id}")

# ruleid: logger-fstring
logger.error(f"Failed for user {uid}: {err}")

# ruleid: logger-fstring
logger.warning(f"Timeout after {seconds}s")
