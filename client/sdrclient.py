import requests
import random
import logging
import yaml
import time

CONFIG_FILE = "config.yml"
NETWORK_RETRY_DELAY = 6
NETWORK_RETRY_ATTEMPTS = 100
NAME_WORDS = 3
FALLBACK_CONFIG = "https://justi.cz/fallback_config.yml"

# Endpoints
PROVISION_ENDPOINT = "provisioning"
POLL_ENDPOINT      = "poll"

class Client:
    def __init__(self, config_file):
        self.config_file = config_file
        self.init_configuration()

    def load_fallback_config(self):
        for i in range(NETWORK_RETRY_ATTEMPTS):
            try:
                r = requests.get(FALLBACK_CONFIG)
                self.config = yaml.load(r.text)
                break
            except requests.exceptions.RequestException, e:
                err = "Couldn't get fallback configuration [try {}/{}]"
                logging.error(err.format(i + 1, NETWORK_RETRY_ATTEMPTS))
            except yaml.YAMLError, e:
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
            except requests.exceptions.RequestException, e:
                err = "Error making api request [try {}/{}]"
                logging.error(err.format(i + 1, NETWORK_RETRY_ATTEMPTS))
            except ValueError, e:
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
            except yaml.YAMLError, e:
                logging.error("Couldn't load from configuration file. Loading fallback")
                self.load_fallback_config()

        # Give ourselves a name if we don't have one
        if self.config.get("name", None) in ("", None):
            self.choose_name()
            self.write_config()

        # At this point, we have *some* configuration, but we might need to
        # provision a key for ourselves
        if self.config.get("api_key", None) in ("", None):
            self.provision_api_key()
            self.write_config()

if __name__ == "__main__":
    c = Client(CONFIG_FILE)

