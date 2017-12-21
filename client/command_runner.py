import logging
import subprocess
import os

class Command:
    def __init__(self, cid, data, results):
        self.cid = cid
        self.data = data
        self.results = results

    def run(self):
        raise NotImplementedError

class ShellCommand(Command):
    def run(self):
        # Ensure we actually received a shell command
        command_text = self.data.get("shell_command", None)
        if command_text is None:
            self.results.put({"cid": self.cid, "result": {"error": "missing shell_command"}})
            return

        # Run the shell command
        p = subprocess.run(command_text,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT,
                           shell=True)

        # Put the results in the results queue
        self.results.put({"cid": self.cid, "result": p.stdout.decode("utf-8")})

class ConfigCommand(Command):
    def run(self):
        # Config commands are special, in that the result is intercepted by
        # the Client and applied there.
        self.results.put({"cid": self.cid,
                          "config": self.data.get("changes", {}),
                          "result": "OK"})

class UpdateCommand(Command):
    def run(self):
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        subprocess.run(["git", "pull"])
        subprocess.run(["sudo", "systemctl", "restart", "sdrclient.service"])

COMMAND_TYPES = { "shell": ShellCommand, "config": ConfigCommand, "update": UpdateCommand }

def run_command(command, results_queue):
    logging.info("Processing command CID={}".format(command["cid"]))
    data = command.get("data", {})
    command_type = COMMAND_TYPES.get(data.get("type", ""), None)
    if command_type is not None:
        c = command_type(command["cid"], data, results_queue)
        c.run()
    else:
        results_queue.put({"cid": command["cid"], "result": {"error": "invalid command type"}})

