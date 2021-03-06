from collections import OrderedDict
import importlib

from artiq.protocols.sync_struct import Notifier


class ResultDB:
    def __init__(self, realtime_results):
        self.realtime_data = Notifier({x: [] for x in realtime_results})
        self.data = Notifier(dict())

    def _request(self, name):
        try:
            return self.realtime_data[name]
        except KeyError:
            try:
                return self.data[name]
            except KeyError:
                self.data[name] = []
                return self.data[name]

    def request(self, name):
        r = self._request(name)
        r.kernel_attr_init = False
        return r

    def set(self, name, value):
        if name in self.realtime_data.read:
            self.realtime_data[name] = value
        else:
            self.data[name] = value


def _create_device(desc, dbh):
    module = importlib.import_module(desc["module"])
    device_class = getattr(module, desc["class"])
    return device_class(dbh, **desc["arguments"])


class DBHub:
    """Connects device, parameter and result databases to experiment.
    Handle device driver creation and destruction.

    """
    def __init__(self, ddb, pdb, rdb):
        self.ddb = ddb
        self.active_devices = OrderedDict()

        self.get_parameter = pdb.request
        self.set_parameter = pdb.set
        self.get_result = rdb.request
        self.set_result = rdb.set

    def get_device(self, name):
        if name in self.active_devices:
            return self.active_devices[name]
        else:
            desc = self.ddb.request(name)
            while isinstance(desc, str):
                # alias
                desc = self.ddb.request(desc)
            dev = _create_device(desc, self)
            self.active_devices[name] = dev
            return dev

    def close(self):
        """Closes all active devices, in the opposite order as they were
        requested.

        Do not use the same ``DBHub`` again after calling
        this function.

        """
        for dev in reversed(list(self.active_devices.values())):
            if hasattr(dev, "close"):
                dev.close()
