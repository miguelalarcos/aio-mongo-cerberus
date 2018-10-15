# SDP: Subscription Data Protocol

import traceback
from asyncio import get_event_loop
import asyncio
import websockets
import jwt
import json
from datetime import datetime
from rethinkdb import r
import os

r.set_loop_type("asyncio")
RT = os.getenv("RT")

async def get_connection():
    return await r.connect(RT, 28015)

methods = {}

def method(f):
    #methods.append(f.__name__)
    async def helper(*args, **kwargs):
        return await f(*args, **kwargs)
    methods[f.__name__] = helper
    return helper

subs = {}

def sub(f):
    #subs.append(f.__name__)
    subs[f.__name__] = f
    return f

def sub_with_aliases(aliases):
    def decorator(f):
        subs[f.__name__] = f
        for alias in aliases:
            subs[alias] = f
        return f
    return decorator

def check(attr, type):
    if not isinstance(attr, type):
        raise CheckError(attr + ' is not of type ' + str(type))

#hooks = {'before_insert': [],
#         'before_update': []
#         }

class MethodError(Exception):
  pass

class CheckError(Exception):
  pass


async def sdp(websocket, path):

    async def watch(sub_id, query): 
        connection = await get_connection()
        
        feed = await query.changes(include_states=True, include_initial=True).run(connection)
        while (await feed.fetch_next()):
            item = await feed.next()
            print(item)
            state = item.get('state')
            if state == 'ready':
                await send_ready(sub_id)
            elif state == 'initializing':
                await send_initializing(sub_id)
            else:
                if item.get('old_val') is None:
                    await send_added(sub_id, item['new_val'])
                elif item.get('new_val') is None: 
                    await send_removed(sub_id, item['old_val']['id'])
                else:
                    await send_changed(sub_id, item['new_val'])            

    async def send(data):
        def helper(x):
            if isinstance(x, datetime):
                return {'$date': x.timestamp()*1000}
            else:
                return x
        message = json.dumps(data, default=helper)
        await websocket.send(message)

    async def send_result(id, result):
        await send({'msg': 'result', 'id': id, 'result': result})

    async def send_error(id, error):
        await send({'msg': 'error', 'id': id, 'error': error})

    async def send_added(sub_id, doc):
        await send({'msg': 'added', 'id': sub_id, 'doc': doc})

    async def send_changed(sub_id, doc):
        await send({'msg': 'changed', 'id': sub_id, 'doc': doc})

    async def send_removed(sub_id, doc_id):
        await send({'msg': 'removed', 'id': sub_id, 'doc_id': doc_id})

    async def send_ready(sub_id):
        await send({'msg': 'ready', 'id': sub_id})

    async def send_initializing(sub_id):
        await send({'msg': 'initializing', 'id': sub_id})    

    async def send_nosub(sub_id, error):
        await send({'msg': 'nosub', 'id': sub_id, 'error': error})

    async def send_nomethod(method_id, error):
        await send({'msg': 'nomethod', 'id': method_id, 'error': error})

    global method

    @method
    async def login(user):
        nonlocal user_id
        user_id = user

    registered_feeds = {}
    #feeds_with_observers = []
    user_id = None
    #remove_observer_from_item = {}
    
    try:
        async for msg in websocket:
            #if msg == 'stop':
            #    return
            print('raw>>>', msg)
            def helper(dct):
                if '$date' in dct.keys():
                    d = datetime.utcfromtimestamp(dct['$date']/1000.0)
                    return d
                    #return d.replace(tzinfo=pytz.UTC)
                return dct
            data = json.loads(msg, object_hook=helper)
            payload = data.get('jwt')
            if payload:
                user = jwt.decode(data['jwt'], 'secret', algorithms=['HS256'])
            else:
                user = {'user': None, roles: ['anonymous']}
            try:
                message = data['msg']
                id = data['id']

                if message == 'method':
                    params = data['params']
                    method = data['method']
                    if method not in methods.keys():
                        await send_nomethod(id, 'method does not exist')
                    else:
                        try:
                            method = methods[method]
                            result = await method(user, **params)
                            await send_result(id, result)
                        except Exception as e:
                          await send_error(id, str(e))
                          traceback.print_tb(e.__traceback__)
                          print(e)
                elif message == 'sub':
                    #name = data['name']
                    params = data['params']
                    if id not in subs.keys():
                        await send_nosub(id, 'sub does not exist')
                    else:
                        query = subs[id](user, **params)
                        #registered_feeds[id] = asyncio.create_task(watch(id, query))
                        registered_feeds[id] = get_event_loop().create_task(watch(id, query))
                        await send_ready(id)
                elif message == 'unsub':
                    if id in registered_feeds.keys():
                        feed = registered_feeds[id]
                        feed.cancel()
                    #if remove_observer_from_item.get(id):
                    #    for remove in remove_observer_from_item[id].values():
                    #        remove()
                    #    del remove_observer_from_item[id]
                    #del registered_feeds[id]
            except KeyError as e:
                await send_error(id, str(e))
            #
    finally:
        #for k in remove_observer_from_item.keys():
        #    for remove in remove_observer_from_item[k].values():
        #        remove()
        for feed in registered_feeds.values():
            print('cancelling feed')
            feed.cancel()
   