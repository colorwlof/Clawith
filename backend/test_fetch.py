import asyncio
import uuid
import sys
import io
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


async def test():
    from app.services.agent_tools import _fetch_feishu_group_messages

    agent_id = uuid.UUID("c9139840-8e21-4967-ba77-514ca4e104ee")
    chat_id = "oc_73c5da219df21160996706e327ff569e"
    args = {"chat_id": chat_id, "limit": 20, "start_time": "172800", "include_own": True}

    result = await _fetch_feishu_group_messages(agent_id, args)
    print(result)


asyncio.run(test())
