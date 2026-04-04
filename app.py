from dotenv import load_dotenv
load_dotenv()

import os
import sys
import time

# Validate required env vars before any other module reads them
REQUIRED_ENV = ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'JWT_SECRET']
missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
if missing:
    print(f"\n[backend] Missing required environment variables: {', '.join(missing)}")
    print('[backend] Copy backend/.env.example → backend/.env and fill in the values.\n')
    sys.exit(1)

from flask import Flask, g, jsonify, request
from flask_cors import CORS

from src.config.oauth import init_oauth
from src.middleware.protect import protect
from src.routes.auth import auth_bp
from src.store import load_pills, save_pills

app = Flask(__name__)
PORT = int(os.getenv('PORT', 3000))

# Secret key used for Flask session (OAuth handshake state only – JWT handles auth)
app.secret_key = os.getenv('SESSION_SECRET', 'change-me-in-production')

# ── Allowed origins ───────────────────────────────────────────────────────────
# Web dev server + Expo web (19006) + Expo Go / metro bundler (8081)
ALLOWED_ORIGINS = [
    os.getenv('CLIENT_URL', 'http://localhost:5173'),
    'http://localhost:19006',
    'http://localhost:8081',
    'https://ziggy3412.github.io',
]
backend_url = os.getenv('BACKEND_URL', '')
if backend_url.startswith('https://'):
    ALLOWED_ORIGINS.append(backend_url)

CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

# ── OAuth (Google) ────────────────────────────────────────────────────────────
init_oauth(app)

# ── Routes ────────────────────────────────────────────────────────────────────
app.register_blueprint(auth_bp, url_prefix='/auth')


@app.get('/api/health')
def health():
    return jsonify({'status': 'ok'})


# ── Protected pill routes ─────────────────────────────────────────────────────
pills = load_pills()


@app.get('/api/pills')
@protect
def get_pills():
    return jsonify([p for p in pills if p.get('userId') == g.user['id']])


@app.post('/api/pills')
@protect
def create_pill():
    pill = {'id': int(time.time() * 1000), 'userId': g.user['id'], **request.get_json()}
    pills.append(pill)
    save_pills(pills)
    return jsonify(pill), 201


@app.delete('/api/pills/<int:pill_id>')
@protect
def delete_pill(pill_id):
    global pills
    pills = [p for p in pills if not (p.get('id') == pill_id and p.get('userId') == g.user['id'])]
    save_pills(pills)
    return '', 204


# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'PillPal backend listening on 0.0.0.0:{PORT} (accessible from all network interfaces)')
    app.run(host='0.0.0.0', port=PORT, debug=os.getenv('NODE_ENV') != 'production')
