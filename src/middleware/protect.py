import os
from functools import wraps
import jwt
from flask import request, jsonify, g


def protect(f):
    """
    Blocks requests without a valid JWT in the `token` httpOnly cookie.
    Also accepts a Bearer token in the Authorization header (mobile clients).
    Sets g.user to the decoded JWT payload.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Cookie-based (web browser)
        token = request.cookies.get('token')

        # Bearer token (mobile – sent from expo-secure-store)
        if not token:
            auth = request.headers.get('Authorization', '')
            if auth.startswith('Bearer '):
                token = auth[7:]

        if not token:
            return jsonify({'error': 'Not authenticated'}), 401

        try:
            g.user = jwt.decode(token, os.getenv('JWT_SECRET'), algorithms=['HS256'])
        except jwt.PyJWTError:
            return jsonify({'error': 'Invalid or expired token'}), 401

        return f(*args, **kwargs)
    return decorated
