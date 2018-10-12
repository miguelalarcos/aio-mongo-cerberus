import jwt

encoded = jwt.encode({'user': 'miguel', 'roles': ['basic', 'admin']}, 'secret', algorithm='HS256').decode('utf-8')
print(encoded)
payload = jwt.decode(encoded, 'secret', algorithms=['HS256'])
print(payload)            