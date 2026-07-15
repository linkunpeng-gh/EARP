from enum import StrEnum
class Permission(StrEnum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    LLM_CALL = "llm_call"
