import multiprocessing as mp
import command_runner
import subprocess
import requests
import logging
import random
import queue
import json
import yaml
import time

CONFIG_FILE = "config.yml"
NAME_WORDS = 3
FALLBACK_CONFIG = "https://justi.cz/fallback_config.yml"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_SYNC_TASK_TIMEOUT = 60
DEFAULT_NETWORK_RETRY_DELAY = 6
DEFAULT_NETWORK_RETRY_ATTEMPTS = 100
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
        # Start a new process to handle the command 
        sp = mp.Process(target = command_runner.run_command,
                        args=(command, self.results))
        sp.start()

        # If we're dealing with it synchronously, wait for it to complete
        if sync:
            try:
                sp.join(timeout=self.config["sync_task_timeout"])
            except TimeoutError as e:
                self.results.put({"cid": command["cid"],
                                  "result": { "error": "Timed out" }})

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
        for i in range(DEFAULT_NETWORK_RETRY_ATTEMPTS):
            try:
                r = requests.get(FALLBACK_CONFIG)
                self.config = yaml.load(r.text)
                break
            except requests.exceptions.RequestException as e:
                err = "Couldn't get fallback configuration [try {}/{}]"
                logging.error(err.format(i + 1, DEFAULT_NETWORK_RETRY_ATTEMPTS))
            except yaml.YAMLError as e:
                logging.critical("Invalid fallback config. Exiting")
                exit(-1)
            time.sleep(DEFAULT_NETWORK_RETRY_DELAY)
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

        if type(r) != dict or type(r.get("api_key", None)) not in [str, bytes]:
            logging.critical("Invalid provisioning response. Exiting")
            exit(-1)

        return r["api_key"]

    def choose_name(self):
        name_parts = []
        with open("/usr/share/dict/words") as fin:
            lines = fin.readlines()
            for i in range(NAME_WORDS):
                name_parts.append(random.choice(lines).strip())
        return " ".join(name_parts)

    def api_request(self, path, body = {}, headers = {}, auth = True):
        for i in range(self.config["network_retry_attempts"]):
            try:
                if auth:
                    headers["Authorization"] = "Bearer " + self.config["api_key"]
                r = requests.post(self.config["api_url"] + path,
                                  json = body,
                                  headers = headers)
                # For some reason we're no longer authorized? Try to provision
                if r.status_code == 403:
                    self.config["api_key"] = self.provision_api_key()
                    self.write_config() 
                return r.json()
            except requests.exceptions.RequestException as e:
                err = "Error making api request [try {}/{}]"
                logging.error(err.format(i + 1, self.config["network_retry_attempts"]))
            except ValueError as e:
                err = "Invalid response from api. [try {}/{}]"
            time.sleep(self.config["network_retry_delay"])
        else:
            logging.critical("API seems down. Exiting")
            exit(-1)

    def set_default_config(self, key, default, empty=(None,), sidefx=False):
        if self.config.get(key, None) in empty:
            # If we have side effects, then the passed value is actually a
            # function that we call
            if sidefx:
                self.config[key] = default()
            else:
                self.config[key] = default

    def init_configuration(self):
        # First attempt to load the configuration from a file
        try:
            with open(self.config_file, "r+") as fin:
                logging.info("Loading configuration from {}".format(self.config_file))
                self.config = yaml.load(fin)
                if type(self.config) != dict:
                    raise yaml.YAMLError
        except (FileNotFoundError, yaml.YAMLError) as e:
            logging.error("Couldn't load from configuration file. Loading fallback")
            self.load_fallback_config()

        # At this point, we have *some* configuration, but we might need to
        # make a name and provision a key for ourselves
        self.set_default_config("network_retry_delay", DEFAULT_NETWORK_RETRY_DELAY)
        self.set_default_config("network_retry_attempts", DEFAULT_NETWORK_RETRY_ATTEMPTS)
        self.set_default_config("sync_task_timeout", DEFAULT_SYNC_TASK_TIMEOUT)
        self.set_default_config("poll_interval", DEFAULT_POLL_INTERVAL)
        self.set_default_config("name", self.choose_name, ("", None), True)
        self.set_default_config("api_key", self.provision_api_key, ("", None), True)

        # Write out to canonicalize and save any changes
        self.write_config()

    def submit_results_and_get_commands(self, completed_commands = {}):
        # Grab all of the results that we can
        results = []
        should_restart = False
        try:
            while True:
                result = self.results.get_nowait()
                # Config/Restart commands are special, and get applied in the client
                if result.get("config", None) is not None:
                    for key, value in result["config"].items():
                        self.config[key] = value
                    self.write_config()
                if result.get("restart", False):
                    should_restart = True
                results.append(result)
        except queue.Empty as e:
            pass

        # Report results back to the server and get new commands
        body = { "completed_commands": results }
        new_commands = self.api_request(POLL_ENDPOINT, body)

        # Restart in order to apply software updates
        if should_restart:
            subprocess.run(["sudo", "systemctl", "restart", "sdrclient.service"])

        # Remove completed commands from the "seen" list, since we will never
        # see them again
        for c in results:
            self.seen_cids.remove(c["cid"])

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

