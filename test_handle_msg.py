from unittest.mock import MagicMock, Mock, patch
import asyncio
import aiounittest
import msdp
from msdp import handle_msg, method, sub

@method
async def add(user, a, b):
    return a + b

@sub
def sub_1(user):
    return {}

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

    async def test_no_sub(self):
        msg = '{"msg": "sub", "id": "sub_not_exists", "params": {}}'
        m = MagicMock()
        async def send(*args, **kwargs):
            m(*args, **kwargs)
        
        await handle_msg(msg, {}, send)
        m.assert_called_with({'msg': 'nosub', 'id': 'sub_not_exists', 'error': 'sub does not exist'})

    async def test_sub(self):
        msg = '{"msg": "sub", "id": "sub_1", "params": {}}'
        m = MagicMock()
        async def send(*args, **kwargs):
            m(*args, **kwargs)
        
        with patch('msdp.get_event_loop') as mock_loop:
            with patch('msdp.watch') as mock_watch:
                mock_create_task = MagicMock()
                mock_loop(return_value=mock_create_task)
                await handle_msg(msg, {}, send)
                mock_watch.assert_called_with('sub_1', {}, send)

