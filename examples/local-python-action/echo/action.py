import json
import os
from pathlib import Path

inputs = json.loads(os.environ["MAKI_INPUTS"])
message = str(inputs.get("message", ""))
prefix = str(inputs.get("prefix", ""))
result = f"{prefix}{message}"

payload = {
    "outputs": {
        "result": result,
        "message": message,
        "prev": os.environ.get("MAKI_PREV", ""),
    }
}
Path(os.environ["MAKI_OUTPUT"]).write_text(json.dumps(payload))
print(result)
