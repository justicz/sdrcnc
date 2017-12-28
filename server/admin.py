from flask import Flask, request, abort, g, jsonify, render_template
from wtforms import StringField, IntegerField
from flask_wtf import FlaskForm, CSRFProtect
from db_helpers import *
import json
import time
import os

app = Flask(__name__)
app.secret_key = os.urandom(32).encode("hex")
CSRFProtect(app)

class RadioDetailsForm(FlaskForm):
    rid = IntegerField('rid')
    description = StringField('Description')

@app.route("/commands", methods=["GET", "POST"])
def commands():
    cmds = query_db('SELECT cid, completed, command, async, result, rid ' \
                    'FROM commands ORDER BY rowid', commit=False)
    return render_template("commands.html", cmds=cmds)

@app.route("/", methods=["GET", "POST"])
def index():
    # Update the descriptions of radios
    radio_deets_form = RadioDetailsForm()
    if radio_deets_form.validate_on_submit():
        rid = radio_deets_form.rid.data
        desc = radio_deets_form.description.data
        query_db('UPDATE radios SET description=? WHERE rid=?', [desc, rid])

    # Get the radios (may have been updated above)
    radios = query_db('SELECT name, description, rid FROM radios')

    return render_template("index.html",
                           radios=radios,
                           radio_deets_form=radio_deets_form)

