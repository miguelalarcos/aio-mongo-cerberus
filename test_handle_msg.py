from unittest.mock import MagicMock, Mock
import asyncio
import aiounittest
from msdp import handle_msg, method

@method
async def add(user, a, b):
    return a + b

class MyTest(aiounittest.AsyncTestCase):
    
    async def test_no_method(self):
        msg = '{"msg": "method", "id": 0, "params": {}, "method": "abc"}'
        m = MagicMock()
        async def send(*args, **kwargs):
            m(*args, **kwargs)
        
        await handle_msg(msg, {}, send)
        m.assert_called_with({'msg': 'nomethod', 'id': 0, 'error': 'method does not exist'})

    async def test_method(self):
        msg = '{"msg": "method", "id": 0, "params": {"a": 1, "b": 2}, "method": "add"}'
        m = MagicMock()
        async def send(*args, **kwargs):
            m(*args, **kwargs)
        
        await handle_msg(msg, {}, send)
        m.assert_called_with({'msg': 'result', 'id': 0, 'result': 3})


