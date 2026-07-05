from enos.schemas import Error

# Merged into every operation: the spec's `default` error envelope response.
DEFAULT_RESPONSES = {"default": {"model": Error, "description": "Error envelope."}}
