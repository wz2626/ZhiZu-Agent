"""Set process privacy defaults before importing model or graph libraries."""

import logging
import os

# Explicit values also prevent dotenv(override=False) from restoring inherited flags.
for prefix in ("LANGCHAIN", "LANGSMITH"):
    for flag in ("TRACING", "TRACING_V2", "DEBUG", "VERBOSE"):
        os.environ[f"{prefix}_{flag}"] = "false"
os.environ["OPENAI_LOG"] = "off"
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
