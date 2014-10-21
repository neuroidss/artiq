import inspect

from artiq.language.core import RuntimeException


# Must be kept in sync with soc/runtime/exceptions.h

class OutOfMemory(RuntimeException):
    """Raised when the runtime fails to allocate memory.

    """
    eid = 0


class RTIOUnderflow(RuntimeException):
    """Raised when the CPU fails to submit a RTIO event early enough (with respect to the event's timestamp).

    """
    eid = 1


# Raised by RTIO driver for regular RTIO.
# Raised by runtime for DDS FUD.
class RTIOSequenceError(RuntimeException):
    """Raised when an event was not submitted with an increasing timestamp.

    """
    eid = 2


exception_map = {e.eid: e for e in globals().values()
                 if inspect.isclass(e)
                 and issubclass(e, RuntimeException)
                 and hasattr(e, "eid")}