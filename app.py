import asyncio
from aiohttp import web
import websockets
from msdp import sdp, method, sub, get_connection
#from rethinkdb import r
from cerberus import Validator
import jwt
from flatten_dict import flatten
import motor.motor_asyncio
from bson import ObjectId
import os
from rethinkdb import r

DB = os.getenv("DB")
RT = os.getenv("RT")

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


schema = {
    'a': {'type': 'integer'},
    'b': {'type': 'string'}
}

v_abc = Validator(schema)

schema_nested = {
    'c': {'type': 'boolean'},
    'd': {'type': 'string'}
}

v_nested = Validator(schema_nested)

validators = {'abc': v_abc, 'abc_nested': v_nested}

def jwt_auth(f):
    async def helper(request):
        try:
            payload = jwt.decode(request.headers['Authorization'], 'secret', algorithms=['HS256'])
            return await f(request, payload)
        except Exception as e:
            print('>>>', e)
            return {'error': 'not valid jwt'}
    return helper

def validate(update=False):
    def decorator(f):
        async def helper(request, payload):
            col = request.match_info.get('col')
            validator = validators[col]
            document = await request.json()             
            if validator.validate(document, update=update):
                return await f(document, request, payload)
            else:
                return web.json_response({'error': 'not valid document'})                 
        return helper
    return decorator

def validate_push(f):
    async def helper(request, payload):
        col = request.match_info.get('col')
        attr = request.match_info.get('push')
        validator = validators[col + '_' + attr]
        document = await request.json()             
        if validator.validate(document):
            return await f(document, request, payload)
        else:
            return web.json_response({'error': 'not valid document'}) 
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

def get(f):
    async def helper(request, payload):
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        document = await db[col].find_one({'_id': ObjectId(_id)})
        document = await f(document)
        document['_id'] = str(document['_id'])
        return web.json_response(document)
    return helper

def insert(f):
    async def helper(document, request, payload):
        col = request.match_info.get('col')
        document = await f(document, request, payload)
        document['__owner'] = payload['user']   
        result = await db[col].insert_one(document)
        document['_id'] = str(result.inserted_id)
        return web.json_response(document)
        #return document 
    return helper

def update(f):
    async def helper(document, request, payload):
        document = await f(document, request, payload)
        document = flatten(document, reducer=point_reducer)
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        await db[col].update_one({'_id': ObjectId(_id)}, {'$set': document})        
        document['_id'] = _id
        return web.json_response(document)
    return helper

def push(f):
    async def helper(document, request, payload):
        document = await f(document, request, payload)
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        attr = request.match_info.get('push')
        document['_id'] = ObjectId()
        await db[col].update_one({'_id': ObjectId(_id)}, {'$push': {attr: document}})        
        document['_id'] = str(document['_id'])
        return web.json_response(document)
    return helper

def pull(f):
    async def helper(request, payload):
        #document = await request.json()
        await f({}, request, payload)
        _id = request.match_info.get('_id')
        col = request.match_info.get('col')
        attr = request.match_info.get('pull')
        sub_id = request.match_info.get('sub_id')
        document = {'_id': ObjectId(sub_id)}
        await db[col].update_one({'_id': ObjectId(_id)}, {'$pull': {attr: document}})        
        return web.json_response({})
    return helper

def json_response(f):
    async def helper(document, request, payload):
        document = await f(document, request, payload)
        return web.json_response(document)
    return helper

async def handle(loop):
    app = web.Application(loop=loop, middlewares=[cors_factory])
    routes = web.RouteTableDef()

    @routes.post('/api/public/login')
    @json_response
    async def login(request):
        body = await request.json()
        return {'jwt': 'xyz'}

    @routes.post('/api/public/test')
    @jwt_auth
    @json_response
    async def handle_post_test(document, *args):
        return document

    @routes.get('/api/default/{col}/{_id}')
    @jwt_auth
    @is_owner
    @get
    async def handle_get(document):      
        return document

    @routes.put('/api/default/{col}/{_id}/push/{push}')
    @jwt_auth
    @is_owner
    @validate_push
    @push
    async def handle_push(document, request, payload):      
        return document

    @routes.put('/api/default/{col}/{_id}/pull/{pull}/{sub_id}')
    @jwt_auth
    @is_owner
    @pull
    async def handle_pull(document, request, payload):      
        print('$pull')

    @routes.post('/api/default/{col}')
    @jwt_auth
    @validate()
    @insert
    async def handle_post(document, request, payload):
        return document       
    
    @routes.put('/api/default/{col}/{_id}')
    @jwt_auth
    @is_owner
    @validate(update=True)
    @update
    async def handle_put(document, request, payload):      
        return document

    app.router.add_routes(routes)
    await loop.create_server(app.make_handler(), '0.0.0.0', 8089)


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
    #return r.table('test').filter(lambda row: (row['x'] < max) & (row['user_id'] == user['user']))


def main():    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(handle(loop))
    print("Server started at port 8089")
    loop.run_until_complete(websockets.serve(sdp, '0.0.0.0', 8888))
    print("Real time server started at port 8888")
    loop.run_forever()
    loop.close()