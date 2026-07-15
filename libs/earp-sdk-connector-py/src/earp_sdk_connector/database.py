from earp_sdk_connector.base import BaseConnector
class DatabaseConnector(BaseConnector):
    protocol = "jdbc"
    async def test_connection(self): raise NotImplementedError("Phase 2")
    async def execute(self, o, p): raise NotImplementedError("Phase 2")
    async def health_check(self): raise NotImplementedError("Phase 2")
