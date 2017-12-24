import logging
import subprocess
import os

class Command:
    def __init__(self, cid, data, sdr, sdr_lock, results):
        self.cid = cid
        self.data = data
        self.sdr = sdr
        self.sdr_lock = sdr_lock
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

class RestartCommand(Command):
    def run(self):
        # Same restart procedure as in UpdateCommand
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

        self.sdr_lock.acquire()

        # (real, imag) samples from the SDR
        samples = []

        try:
            # Grab the samples
            self.sdr.sample_rate = int(self.data["sample_rate"])
            self.sdr.center_freq = int(self.data["center_freq"])
            self.sdr.freq_correction = int(self.data["freq_correction"])
            self.sdr.gain = self.data["gain"]
            samples = self.sdr.read_samples(self.data["num_samples"])
        except Exception as e:
            # Deal with any errors talking to the hardware
            self.results.put({"cid": self.cid,
                              "result": {"error": "SDR exception: {}".format(e)}})
            self.sdr_lock.release()
            return

        self.sdr_lock.release()

        self.results.put({"cid": self.cid,
                          "result": [(s.real, s.imag) for s in samples]})


COMMAND_TYPES = { "shell": ShellCommand,
                  "config": ConfigCommand,
                  "update": UpdateCommand,
                  "restart": RestartCommand,
                  "sdr": SDRCommand }

def run_command(command, results_queue, sdr, sdr_lock):
    logging.info("Processing command CID={}".format(command["cid"]))
    data = command.get("data", {})
    command_type = COMMAND_TYPES.get(data.get("type", ""), None)
    if command_type is not None:
        c = command_type(command["cid"], data, sdr, sdr_lock, results_queue)
        try:
            c.run()
        except Exception as e:
            results_queue.put({"cid": command["cid"],
                               "result": {"error": "command raised exception {}".format(e)}})
    else:
        results_queue.put({"cid": command["cid"], "result": {"error": "invalid command type"}})

