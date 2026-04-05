import os
import time

import jwt
from flask import Blueprint, g, jsonify, redirect, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from src.config.oauth import oauth
from src.middleware.protect import protect
from src.store import upsert_user

auth_bp = Blueprint('auth', __name__)

CLIENT_URL = os.getenv('CLIENT_URL', 'http://localhost:5173')
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def issue_jwt(user):
    payload = {**user, 'exp': int(time.time()) + COOKIE_MAX_AGE}
    return jwt.encode(payload, os.getenv('JWT_SECRET'), algorithm='HS256')


def set_token_cookie(response, token):
    # When the backend is behind HTTPS (e.g. ngrok) the frontend may be on a
    # different origin (localhost:5173). SameSite=None; Secure is required so
    # the browser sends the cookie on cross-origin credentialed fetch requests.
    is_https = os.getenv('BACKEND_URL', '').startswith('https://')
    response.set_cookie(
        'token',
        token,
        httponly=True,
        secure=is_https or os.getenv('NODE_ENV') == 'production',
        samesite='None' if is_https else 'Lax',
        max_age=COOKIE_MAX_AGE,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

# Client-side token exchange (used by @react-oauth/google on the frontend)
# Receives the Google ID token credential, verifies it, issues JWT cookie.
@auth_bp.post('/google')
def google_token_exchange():
    data = request.get_json() or {}
    credential = data.get('credential')
    if not credential:
        return jsonify({'error': 'credential is required'}), 400

    try:
        payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            os.getenv('GOOGLE_CLIENT_ID'),
        )
        user = {
            'id': payload['sub'],
            'displayName': payload.get('name'),
            'email': payload.get('email'),
            'photo': payload.get('picture'),
        }
        profile = upsert_user(user['id'], user)
        token = issue_jwt(user)
        response = jsonify({'user': {**user, 'onboarded': profile['onboarded']}, 'token': token})
        set_token_cookie(response, token)
        return response
    except Exception:
        return jsonify({'error': 'Invalid Google credential'}), 401


# Step 1a – redirect web browser to Google's consent screen
@auth_bp.get('/google')
def google_redirect():
    callback_url = f"{os.getenv('BACKEND_URL', 'http://localhost:3000')}/auth/google/callback"
    return oauth.google.authorize_redirect(callback_url)


# Step 1b – mobile: pass state='mobile' so the callback knows to deep-link
@auth_bp.get('/google/mobile')
def google_redirect_mobile():
    callback_url = f"{os.getenv('BACKEND_URL', 'http://localhost:3000')}/auth/google/callback"
    return oauth.google.authorize_redirect(callback_url, state='mobile')


# Step 2 – Google redirects back here with an authorization code
@auth_bp.get('/google/callback')
def google_callback():
    try:
        token_data = oauth.google.authorize_access_token()
        userinfo = token_data.get('userinfo') or oauth.google.userinfo()
        user = {
            'id': userinfo['sub'],
            'displayName': userinfo.get('name'),
            'email': userinfo.get('email'),
            'photo': userinfo.get('picture'),
        }
        upsert_user(user['id'], user)
        jwt_token = issue_jwt(user)
        is_mobile = request.args.get('state') == 'mobile'

        if is_mobile:
            return redirect(f'pillpal://auth?token={jwt_token}')

        response = redirect(CLIENT_URL)
        set_token_cookie(response, jwt_token)
        return response
    except Exception:
        return redirect('/auth/failed')


# Return the currently logged-in user (reads JWT cookie via protect middleware)
@auth_bp.get('/me')
@protect
def me():
    user = {k: v for k, v in g.user.items() if k not in ('iat', 'exp')}
    return jsonify({'user': user})


# Clear the JWT cookie
@auth_bp.post('/logout')
def logout():
    response = jsonify({'message': 'Logged out'})
    response.delete_cookie('token', httponly=True, samesite='Lax')
    return response


# Fallback when Google auth fails
@auth_bp.get('/failed')
def auth_failed():
    return jsonify({'error': 'Google authentication failed'}), 401
