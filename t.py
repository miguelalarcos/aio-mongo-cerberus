import jwt

encoded = jwt.encode({'user': 'miguel', 'roles': ['basic', 'admin']}, 'secret', algorithm='HS256')
print(encoded)