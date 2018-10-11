import asyncio
from aiohttp import web
import websockets
from msdp import sdp, method, sub, get_connection
from rethinkdb import r
from cerberus import Validator
import jwt
from flatten_dict import flatten
import motor.motor_asyncio
from bson import ObjectId
import os
#from dotenv import load_dotenv 
#load_dotenv()

r.set_loop_type("asyncio")

DB = os.getenv("DB")
RT = os.getenv("RT")

ALLOWED_HEADERS = ','.join((
    'content-type',
    'accept',
    'origin',
    'authorization',
    'x-requested-with',
    'x-csrftoken',
    ))

def set_cors_headers (request, response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Authorization, Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'
    #response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

async def cors_factory (app, handler):
    async def cors_handler (request):
        # preflight requests
        if request.method == 'OPTIONS':
            return set_cors_headers(request, web.Response())
        else:
            response = await handler(request)
            return set_cors_headers(request, response)
    return cors_handler

client = motor.motor_asyncio.AsyncIOMotorClient(DB, 27017)
db = client.test

def point_reducer(k1, k2):
    if k1 is None:
        return k2
    else:
        return k1 + "." + k2


#headers = {}
#headers['Access-Control-Allow-Origin'] = '*'
#headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
#headers['Access-Control-Allow-Headers'] = 'Authorization, Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'        

schema = {'name': {'type': 'string'}, 
          'contact': {
            'type': 'dict', 'schema': {
                'email': {'type': 'string'},
                'phone': {'type': 'string'}
            }}}
v_car = Validator(schema)

validators = {'car': v_car}

def jwt_auth(f):
    async def helper(request):
        try:
            payload = jwt.decode(request.headers['Authorization'], 'secret', algorithms=['HS256'])
            return await f(request, payload)
        except:
            return {'error': 'not valid jwt'}
    return helper

def validate(f):
    async def helper(request, payload):
        col = request.match_info.get('col')
        validator = validators[col]
        document = await request.json()             
        if validator.validate(document):
            document['__owner'] = payload['user']   
            return await f(document, request, payload)
        else:
            #return web.json_response({'error': 'not valid document'}, headers=headers) 
            return {'error': 'not valid document'}
    return helper

def has_role(role):
    def decorator(f):
        async def helper(request, payload):
            if role in payload['roles']:
                return await f(request, payload)
            else:
                return {'error': 'not authorized'}
        return helper
    return decorator

def is_owner(f):
    async def helper(request, payload):
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        old_doc = await db[col].find_one({'_id': ObjectId(_id)})
        if payload['user'] == old_doc["__owner"]:
            return await f(request, payload)
        else:
            return {'error': 'not authorized'}
    return helper

def insert(f):
    async def helper(document, request, payload):
        col = request.match_info.get('col')
        document = await f(document, request, payload)
        result = await db[col].insert_one(document)
        document['_id'] = str(result.inserted_id)
        return document #await f(document, request, payload)
    return helper

def update(f):
    async def helper(document, request, payload):
        original = document
        document = flatten(document, reducer=point_reducer)
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        await db[col].update_one({'_id': ObjectId(_id)}, {'$set': document})        
        return await f(original, request, payload)
    return helper

def json_response(f):
    async def helper(document, request, payload):
        document = await f(document, request, payload)
        return web.json_response(document)#, headers=headers)
    return helper

async def handle(loop):
    app = web.Application(loop=loop, middlewares=[cors_factory])
    routes = web.RouteTableDef()

    @routes.post('/login')
    @json_response
    def login(request):
        body = await request.json()
        print('body:', body)
        return {'login': 'ok'}

    @routes.post('/test')
    @jwt_auth
    @json_response
    async def handle_post_test(document, *args):
        return {'test': 'ok'}

    @routes.post('/{col}')
    @jwt_auth
    @validate
    @insert
    @json_response
    async def handle_post(document, request, payload):
        return document       
    
    @routes.put('/{col}/{_id}')
    @jwt_auth
    @is_owner
    @validate
    @update
    @json_response
    async def handle_put(document, request, payload):      
        return document

    app.router.add_routes(routes)
    await loop.create_server(app.make_handler(), '0.0.0.0', 8089, ssl=None)

@method
async def add(user, a, b):
    return a + b

@method
async def increment(user, id, value):
    connection = await get_connection()
    await r.table('test').get(id).update({"x": r.row["x"]+value}).run(connection)

@sub
def x_less_than(user, max):
    return r.table('test').filter(lambda row: (row['x'] < max))
    #return r.table('test').filter(lambda row: (row['x'] < max) & (row['user_id'] == user.id))

def main():    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(handle(loop))
    print("Server started at port 8089")
    loop.run_until_complete(websockets.serve(sdp, '0.0.0.0', 8888, ssl=None))
    print("Real time server started at port 8888")
    loop.run_forever()
    loop.close()