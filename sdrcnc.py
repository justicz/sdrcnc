from flask import Flask, request, abort, g, jsonify
from db_helpers import *
import time
import os

app = Flask(__name__)

PASSWORD_TIMEOUT = 1
HTTP_AUTHORIZATION = 'Authorization'
PARAM_COMPLETED = 'completed_commands'
API_KEY_BYTES = 32

# Note: disable after deployment!
PROVISIONING_ENABLED = True

@app.before_request
def authenticate():
    # Bypass auth if we're hitting the provisioning endpoint
    if PROVISIONING_ENABLED and request.endpoint == "provisioning":
        return

    # Grab the authorization header and parse out the auth token
    auth_header = request.headers.get(HTTP_AUTHORIZATION, '')
    values = auth_header.split(" ")
    if len(values) != 2:
        time.sleep(PASSWORD_TIMEOUT)
        abort(403)
    auth_token = values[1]

    # Ensure it's a valid auth token
    radio = query_db('SELECT rid FROM radios WHERE api_key = ?',
                     [auth_token], one=True, commit=False)
    if radio is None:
        time.sleep(PASSWORD_TIMEOUT)
        abort(403)

    # Set g.rid so the we can log the access later
    g.rid = radio[0]

def generate_api_key():
    return os.urandom(API_KEY_BYTES).encode("hex")

def get_commands():
    # cid is autoincrement, and we never delete from the commands DB, so this
    # is OK. The internet confirms that order by rowid is OK
    return query_db('SELECT cid, command FROM commands ' \
                    'WHERE completed = 0 AND ' \
                    'rid = ? ORDER BY rowid', [g.rid], commit=False)

def process_completed_commands(commands):
    # for each completed command, mark it as completed and record the results
    for command in commands:
        if type(command) != dict:
            abort(400)
        cid, result = command['cid'], command['result']
        query_db('UPDATE commands SET '
                 'completed = 1, ' \
                 'result = ? ' \
                 'WHERE cid = ? '\
                 'AND rid = ? '\
                 'AND completed = 0', [result, cid, g.rid])

@app.route("/provisioning", methods=["POST"], endpoint="provisioning")
def provisioning():
    # Do some basic validation
    request_data = request.get_json()
    if request_data is None or type(request_data) != dict:
        abort(400)
    if type(request_data.get("name", None)) not in [str, unicode]:
        abort(400)

    api_key = generate_api_key()

    # Generate an API key and add this radio to our database
    query_db('INSERT INTO radios (api_key, name) VALUES (?, ?)',
             [api_key, request_data["name"]])

    return jsonify({ "api_key": api_key })

@app.route("/poll", methods=["POST"])
def poll():
    # Parse json from the request
    request_data = request.get_json()
    if request_data is None or type(request_data) != dict:
        abort(400)

    # Mark commands that the radio has completed and collect responses
    completed_commands = request_data.get(PARAM_COMPLETED, [])
    process_completed_commands(completed_commands)

    # Reply with any new/remaining commands
    commands = get_commands()
    return jsonify(commands)

