import multiprocessing as mp
import requests
import logging
import random
import queue
import json
import yaml
import time

CONFIG_FILE = "config.yml"
NETWORK_RETRY_DELAY = 6
NETWORK_RETRY_ATTEMPTS = 100
NAME_WORDS = 3
FALLBACK_CONFIG = "https://justi.cz/fallback_config.yml"
DEFAULT_POLL_INTERVAL = 5
PROVISION_ENDPOINT = "provisioning"
POLL_ENDPOINT      = "poll"

class Client:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config = {}
        self.init_configuration()

        # Keeps track of which commands we've seen to avoid dupes
        self.seen_cids = set()
        # A queue of commands to execute in order
        self.sync_commands = mp.Queue()
        # A queue of commands to execute whenever
        self.async_commands = mp.Queue()
        # A queue of command results
        self.results = mp.Queue()

        # Start the worker processes to deal with those queues
        self.start_workers()

    def process_command(self, command, sync):
        if sync:
            res = {
                "cid": command["cid"],
                "result": "Processed command with cid {}".format(command["cid"])
            }
            self.results.put(res)
        else:
            # Spin up a new process and calls the sync version
            sp = mp.Process(target = self.process_command, args=(command, True))
            sp.start()

    def process_sync_commands(self):
        while True:
            next_command = self.sync_commands.get()
            self.process_command(next_command, True)

    def process_async_commands(self):
        while True:
            next_command = self.async_commands.get()
            self.process_command(next_command, False)

    def start_workers(self):
        self.p_sync = mp.Process(target = self.process_sync_commands)
        self.p_async = mp.Process(target = self.process_async_commands)
        self.p_sync.start()
        self.p_async.start()

    def load_fallback_config(self):
        for i in range(NETWORK_RETRY_ATTEMPTS):
            try:
                r = requests.get(FALLBACK_CONFIG)
                self.config = yaml.load(r.text)
                break
            except requests.exceptions.RequestException as e:
                err = "Couldn't get fallback configuration [try {}/{}]"
                logging.error(err.format(i + 1, NETWORK_RETRY_ATTEMPTS))
            except yaml.YAMLError as e:
                logging.critical("Invalid fallback config. Exiting")
                exit(-1)
            time.sleep(NETWORK_RETRY_DELAY)
        else:
            logging.critical("Couldn't load any config. Exiting")
            exit(-1)
        logging.info("Successfully loaded fallback configuration.")

    def write_config(self):
        with open(self.config_file, "w") as fout:
            fout.write(yaml.dump(self.config))

    def provision_api_key(self):
        r = self.api_request(PROVISION_ENDPOINT,
                             { "name": self.config["name"] },
                             auth = False)

        if type(r) != dict or type(r.get("api_key", None)) not in [str, unicode]:
            logging.critical("Invalid provisioning response. Exiting")
            exit(-1)

        self.config["api_key"] = r["api_key"]

    def choose_name(self):
        name_parts = []
        with open("/usr/share/dict/words") as fin:
            lines = fin.readlines()
            for i in range(NAME_WORDS):
                name_parts.append(random.choice(lines).strip())
        self.config["name"] = " ".join(name_parts)

    def api_request(self, path, body = {}, headers = {}, auth = True):
        for i in range(NETWORK_RETRY_ATTEMPTS):
            try:
                if auth:
                    headers["Authorization"] = "Bearer " + self.config["api_key"]
                r = requests.post(self.config["api_url"] + path,
                                  json = body,
                                  headers = headers)
                return r.json()
            except requests.exceptions.RequestException as e:
                err = "Error making api request [try {}/{}]"
                logging.error(err.format(i + 1, NETWORK_RETRY_ATTEMPTS))
            except ValueError as e:
                err = "Invalid response from api. [try {}/{}]"
            time.sleep(NETWORK_RETRY_DELAY)
        else:
            logging.critical("API seems down. Exiting")
            exit(-1)
 
    def init_configuration(self):
        # First attempt to load the configuration from a file
        with open(self.config_file, "r+") as fin:
            try:
                logging.info("Loading configuration from {}".format(self.config_file))
                self.config = yaml.load(fin)
            except yaml.YAMLError as e:
                logging.error("Couldn't load from configuration file. Loading fallback")
                self.load_fallback_config()

        # Give ourselves a name if we don't have one
        if self.config.get("name", None) in ("", None):
            self.choose_name()

        # At this point, we have *some* configuration, but we might need to
        # provision a key for ourselves
        if self.config.get("api_key", None) in ("", None):
            self.provision_api_key()

        # Ensure some other defaults are set
        if self.config.get("poll_interval", None) is None:
            self.config["poll_interval"] = DEFAULT_POLL_INTERVAL

        # Write out to canonicalize and save any changes
        self.write_config()

    def submit_results_and_get_commands(self, completed_commands = {}):

        # Grab all of the results that we can
        results = []
        try:
            while True:
                results.append(self.results.get_nowait())
        except queue.Empty as e:
            pass

        # Report results back to the server and get new commands
        body = { "completed_commands": results }
        new_commands = self.api_request(POLL_ENDPOINT, body)
        for c in new_commands:
            # Ignore commands we've already seen
            if c["cid"] in self.seen_cids:
                continue
            # Mark that we've seen this command
            self.seen_cids.add(c["cid"])
            # Add sync and async commands to their queues
            if c.get("async", False):
                self.async_commands.put(c)
            else:
                self.sync_commands.put(c)

    def poll_forever(self):
        while True:
            self.submit_results_and_get_commands()
            time.sleep(self.config["poll_interval"])

if __name__ == "__main__":
    c = Client(CONFIG_FILE)
    c.poll_forever()

