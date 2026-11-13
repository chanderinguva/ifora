"""Remove one-use OAuth codes and state from Uvicorn access-log request targets."""
import logging


class OAuthAccessFilter(logging.Filter):
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str) and args[2].split("?", 1)[0] == "/api/v1/admin/recipe-connections/oauth/callback":
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def install():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, OAuthAccessFilter) for f in logger.filters):
        logger.addFilter(OAuthAccessFilter())
