"""Parse the observed legacy status reply without retaining metadata."""

import re

_STATUS = re.compile(
    r"ACK STATUS:(?P<status>(?:PED |FULL |SINGLE )?"
    r"(?:CLOSED|OPEN|OPENED|OPENING|CLOSING|CLOSEING|STOPPED)),"
    r"(?P<position>[0-9]{1,3})"
)


def parse_status_reply(payload: object) -> dict:
    """Accept only known status words and travel values from 0 to 100."""
    if not isinstance(payload, str):
        return {}
    match = _STATUS.fullmatch(payload.split(";", 1)[0].strip())
    if match is None or int(match["position"]) > 100:
        return {}
    return {"ack": "ACK STATUS", "status": match["status"],
            "status_position": int(match["position"])}
