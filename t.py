import jwt

encoded = jwt.encode({'user': 'miguel'}, 'secret', algorithm='HS256')
print(encoded)