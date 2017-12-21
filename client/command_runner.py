import logging
import subprocess

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

COMMAND_TYPES = { "shell": ShellCommand }

def run_command(command, results_queue):
    logging.info("Processing command CID={}".format(command["cid"]))
    data = command.get("data", {})
    command_type = COMMAND_TYPES.get(data.get("type", ""), None)
    if command_type is not None:
        c = command_type(command["cid"], data, results_queue)
        c.run()
    else:
        results_queue.put({"cid": command["cid"], "result": {"error": "invalid command type"}})

