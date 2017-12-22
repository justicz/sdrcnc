from rtlsdr import RtlSdr
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
        # Like the config command, the update command also causes action to be
        # taken in the Client (restarting the service)
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        subprocess.run(["git", "pull"])
        self.results.put({"cid": self.cid,
                          "restart": True,
                          "result": "OK"})

class SDRCommand(Command):
    def run(self):
        # Ensure we were passed all of the required args
        required_keys = ["sample_rate", "center_freq",
                         "freq_correction", "num_samples", "gain"]
        if not all([k in self.data for k in required_keys]):
            self.results.put({"cid": self.cid, "result": {"error": "missing args"}})
            return

        # Initialize the SDR
        sdr = RtlSdr()

        # Report the samples
        sdr.sample_rate = int(self.data["sample_rate"])
        sdr.center_freq = int(self.data["center_freq"])
        sdr.freq_correction = int(self.data["freq_correction"])
        sdr.gain = self.data["gain"]
        samples = sdr.read_samples(self.data["num_samples"])
        self.results.put({"cid": self.cid,
                          "result": [(s.real, s.imag) for s in samples]})

        # Clean up the SDR connection
        sdr.close()

COMMAND_TYPES = { "shell": ShellCommand,
                  "config": ConfigCommand,
                  "update": UpdateCommand,
                  "sdr": SDRCommand }

def run_command(command, results_queue):
    logging.info("Processing command CID={}".format(command["cid"]))
    data = command.get("data", {})
    command_type = COMMAND_TYPES.get(data.get("type", ""), None)
    if command_type is not None:
        c = command_type(command["cid"], data, results_queue)
        try:
            c.run()
        except Exception as e:
            results_queue.put({"cid": command["cid"],
                               "result": {"error": "command raised exception {}".format(e)}})
    else:
        results_queue.put({"cid": command["cid"], "result": {"error": "invalid command type"}})

