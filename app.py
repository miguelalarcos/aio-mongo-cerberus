import asyncio
from aiohttp import web
from cerberus import Validator
import jwt
from flatten_dict import flatten
import motor.motor_asyncio
from bson import ObjectId

client = motor.motor_asyncio.AsyncIOMotorClient('db', 27017)
db = client.test

def point_reducer(k1, k2):
    if k1 is None:
        return k2
    else:
        return k1 + "." + k2


headers = {}
headers['Access-Control-Allow-Origin'] = '*'
headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
headers['Access-Control-Allow-Headers'] = 'Authorization, Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'        

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
            #print('***************', validator.errors)
            return web.json_response({'error': 'not valid document'}, headers=headers) 
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
        #old_doc = {"name": "oki", "__owner": "miguel"}   
        if payload['user'] == old_doc["__owner"]:
            return await f(request, payload)
        else:
            return {'error': 'not authorized'}
    return helper

def insert(f):
    async def helper(document, request, payload):
        col = request.match_info.get('col')
        result = await db[col].insert_one(document)
        document['_id'] = str(result.inserted_id)
        return await f(document, request, payload)
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
    async def helper(document, *args):
        await f(document, *args)
        return web.json_response(document, headers=headers)
    return helper

async def handle(loop):
    app = web.Application(loop=loop)
    routes = web.RouteTableDef()

    @routes.post('/test')
    @jwt_auth
    async def handle_post_test(document, *args):
        return web.json_response({'test': 'ok'}, headers=headers)

    @routes.post('/{col}')
    @jwt_auth
    @validate
    @insert
    @json_response
    async def handle_post(document, *args):
        print(document)       
    
    @routes.put('/{col}/{_id}')
    @jwt_auth
    @is_owner
    @validate
    @update
    @json_response
    async def handle_put(document, *args):      
        print(document)

    app.router.add_routes(routes)
    await loop.create_server(app.make_handler(), '0.0.0.0', 8089)
    
def main():    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(handle(loop))
    print("Server started at http://0.0.0.0:8089")
    loop.run_forever()
    loop.close()