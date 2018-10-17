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

hooks = {'before_insert': [],
         'before_update': []
         }

class MethodError(Exception):
  pass

class CheckError(Exception):
  pass

def helper_dumps(x):
    if isinstance(x, datetime):
        return {'$date': x.timestamp()*1000}
    else:
        return x

async def sdp(websocket, path):

    async def send(data):
        message = json.dumps(data, default=helper_dumps)
        await websocket.send(message)

    registered_feeds = {}
    
    try:
        async for msg in websocket:
            await handle_msg(msg, registered_feeds, send)            
    finally:
        for feed in registered_feeds.values():
            print('cancelling feed')
            feed.cancel()

async def send_result(id, result, send):
    await send({'msg': 'result', 'id': id, 'result': result})

async def send_error(id, error, send):
    await send({'msg': 'error', 'id': id, 'error': error})

async def send_added(sub_id, doc, send):
    await send({'msg': 'added', 'id': sub_id, 'doc': doc})

async def send_changed(sub_id, doc, send):
    await send({'msg': 'changed', 'id': sub_id, 'doc': doc})

async def send_removed(sub_id, doc_id, send):
    await send({'msg': 'removed', 'id': sub_id, 'doc_id': doc_id})

async def send_ready(sub_id, send):
    await send({'msg': 'ready', 'id': sub_id})

async def send_initializing(sub_id, send):
    await send({'msg': 'initializing', 'id': sub_id})    

async def send_nosub(sub_id, error, send):
    await send({'msg': 'nosub', 'id': sub_id, 'error': error})

async def send_nomethod(method_id, error, send):
    await send({'msg': 'nomethod', 'id': method_id, 'error': error})

def helper(dct):
    if '$date' in dct.keys():
        d = datetime.utcfromtimestamp(dct['$date']/1000.0)
        return d
        #return d.replace(tzinfo=pytz.UTC)
    return dct

async def handle_msg(msg, registered_feeds, send):
    print('raw>>>', msg)
    try:
        data = json.loads(msg, object_hook=helper)
    except:
        return await send_error(None, 'error in json.loads', send)
    
    id = data.get('id')
    payload = data.get('jwt')
    if payload:
        try:
            user = jwt.decode(data['jwt'], 'secret', algorithms=['HS256'])
        except jwt.DecodeError:
            return await send_error(id, 'error decode jwt', send)
    else:
        user = None
    try:
        message = data['msg']        

        if message == 'method':
            params = data['params']
            method = data['method']
            if method not in methods.keys():
                await send_nomethod(id, 'method does not exist', send)
            else:
                method = methods[method]
                result = await method(user, **params)
                await send_result(id, result, send)
        elif message == 'sub':
            params = data['params']
            if id not in subs.keys():
                await send_nosub(id, 'sub does not exist', send)
            else:
                query = subs[id](user, **params)
                registered_feeds[id] = get_event_loop().create_task(watch(id, query, send))
                await send_ready(id, send) #why??? creo que debe ser borrada
        elif message == 'unsub':
            if id in registered_feeds.keys():
                feed = registered_feeds[id]
                feed.cancel()
    except KeyError as e:
        await send_error(id, 'key error ' + str(e), send)
    except Exception as e:
        await send_error(id, str(e), send)

async def watch(sub_id, query, send): 
    connection = await get_connection()
    
    feed = await query.changes(include_states=True, include_initial=True).run(connection)
    while (await feed.fetch_next()):
        item = await feed.next()
        await handle_watch(item, sub_id, send)
    
async def handle_watch(item, sub_id, send):
    state = item.get('state')
    if state == 'ready':
        await send_ready(sub_id, send)
    elif state == 'initializing':
        await send_initializing(sub_id, send)
    else:
        if item.get('old_val') is None:
            await send_added(sub_id, item['new_val'], send)
        elif item.get('new_val') is None: 
            await send_removed(sub_id, item['old_val']['id'], send)
        else:
            await send_changed(sub_id, item['new_val'], send)           

