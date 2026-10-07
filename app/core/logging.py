import json
import logging
import traceback
import uuid


def log_error(event: str, error: Exception, **context) -> str:
    """Keep stack locations while excluding exception strings that may contain secrets."""
    request_id = str(uuid.uuid4())
    frames = traceback.extract_tb(error.__traceback__)
    logging.getLogger("aera").error(
        json.dumps(
            {
                "event": event,
                "request_id": request_id,
                "status": "failed",
                "error_type": type(error).__name__,
                "stack": [
                    {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in frames
                ],
                **context,
            }
        )
    )
    return request_id
