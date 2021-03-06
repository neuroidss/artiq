import logging
import ctypes
import struct
from artiq.language.units import dB, check_unit, Quantity

logger = logging.getLogger("lda")


class HidError(Exception):
    pass


class Ldasim:
    """Lab Brick Digital Attenuator simulation controller.
    """

    def __init__(self):
        self._attenuation = None
        self._att_max = 63*dB
        self._att_step_size = 0.25*dB

    def get_attenuation(self):
        """Reads last attenuation value set to the simulated device.

        :return: Returns the attenuation value in dB, or None if it was
                 never set.
        :rtype: float
        """

        return self._attenuation

    def set_attenuation(self, attenuation):
        """Stores the new attenuation value and prints it to console.

        :param attenuation: The attenuation value in dB.
        :type attenuation: int, float or Fraction
        """

        if isinstance(attenuation, Quantity):
            check_unit(attenuation, 'dB')
        else:
            att = attenuation*dB

        if att > self._att_max:
            raise ValueError('Cannot set attenuation {} > {}'
                             .format(att, self._att_max))
        elif att < 0*dB:
            raise ValueError('Cannot set attenuation {} < 0'.format(att))
        elif att % self._att_step_size != 0*dB:
            raise ValueError('Cannot set attenuation {} with step size {}'
                             .format(att, self._att_step_size))
        else:
            att = round(att.amount*4)/4. * dB
            print("[LDA-sim] setting attenuation to {}".format(att))
            self._attenuation = att


class Lda:
    """Lab Brick Digital Attenuator controller.

    This controller depends on the hidapi library.

    On Linux you should install hidapi-libusb shared library in a directory
    listed in your LD_LIBRARY_PATH or in the conventional places (/usr/lib,
    /lib, /usr/local/lib). This can be done either from hidapi sources
    or by installing the libhidapi-libusb0 binary package on Debian-like OS.

    On Windows you should put hidapi.dll shared library in the same directory
    as the controller.

    """
    _vendor_id = 0x041f
    _product_ids = {
        "LDA-102": 0x1207,
        "LDA-602": 0x1208,
        "LDA-302P-1": 0x120E,
    }
    _max_att = {
        "LDA-102": 63*dB,
        "LDA-602": 63*dB,
        "LDA-302P-1": 63*dB
    }
    _att_step_size = {
        "LDA-102": 0.5*dB,
        "LDA-602": 0.5*dB,
        "LDA-302P-1": 1.0*dB
    }

    def __init__(self, serial=None, product="LDA-102"):
        """
        :param serial: The serial number.
        :param product: The product identifier string: LDA-102, LDA-602.
        """

        from artiq.devices.lda.hidapi import hidapi
        self.hidapi = hidapi
        self.product = product
        if serial is None:
            serial = next(self.enumerate(product))
        self._dev = self.hidapi.hid_open(self._vendor_id,
                                         self._product_ids[product], serial)
        assert self._dev

    @classmethod
    def enumerate(cls, product):
        from artiq.devices.lda.hidapi import hidapi
        devs = hidapi.hid_enumerate(cls._vendor_id,
                                    cls._product_ids[product])
        try:
            dev = devs
            while dev:
                yield dev[0].serial
                dev = dev[0].next
        finally:
            hidapi.hid_free_enumeration(devs)

    def _check_error(self, ret):
        if ret < 0:
            err = self.hidapi.hid_error(self._dev)
            raise HidError("{}: {}".format(ret, err))
        return ret

    def write(self, command, length, data=bytes()):
        """Writes a command to the Lab Brick device.

        :param command: command ID.
        :param length: number of meaningful bytes in the data array.
        :param data: a byte array containing the payload of the command.
        """

        # 0 is report id/padding
        buf = struct.pack("BBB6s", 0, command, length, data)
        res = self._check_error(self.hidapi.hid_write(self._dev, buf,
                                                      len(buf)))
        assert res == len(buf), res

    def set(self, command, data):
        """Sends a SET command to the Lab Brick device.

        :param command: command ID, must have most significant bit set.
        :param data: payload of the command.
        """

        assert command & 0x80
        assert data
        self.write(command, len(data), data)

    def get(self, command, length, timeout=1000):
        """Sends a GET command to read back some value of the Lab Brick device.

        :param int command: Command ID, most significant bit must be cleared.
        :param int length: Length of the command, "count" in the datasheet.
        :param int timeout: Timeout of the HID read in ms.
        :return: Returns the value read from the device.
        :rtype: bytes
        """

        assert not command & 0x80
        status = None
        self.write(command, length)
        buf = ctypes.create_string_buffer(8)
        while status != command:
            res = self._check_error(self.hidapi.hid_read_timeout(self._dev,
                                    buf, len(buf), timeout))
            assert res == len(buf), res
            status, length, data = struct.unpack("BB6s", buf.raw)
            data = data[:length]
        logger.info("%s %s %r", command, length, data)
        return data

    def get_attenuation(self):
        """Reads attenuation value from Lab Brick device.

        :return: Returns the attenuation value in dB.
        :rtype: float
        """

        return (ord(self.get(0x0d, 1))/4.) * dB

    def set_attenuation(self, attenuation):
        """Sets attenuation value of the Lab Brick device.

        :param attenuation: Attenuation value in dB.
        :type attenuation: int, float or Fraction
        """

        if isinstance(attenuation, Quantity):
            check_unit(attenuation, 'dB')
        else:
            att = attenuation*dB

        if att > self._max_att[self.product]:
            raise ValueError('Cannot set attenuation {} > {}'
                             .format(att, self._max_att[self.product]))
        elif att < 0:
            raise ValueError('Cannot set attenuation {} < 0'.format(att))
        elif att % self._att_step_size[self.product] != 0:
            raise ValueError('Cannot set attenuation {} with {} step size'
                             .format(att, self._att_step_size[self.product]))
        else:
            self.set(0x8d, bytes([int(round(att.amount*4))]))
