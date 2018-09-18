import sys

if sys.version_info < (3, 0):
    from Queue import PriorityQueue
else:
    from queue import PriorityQueue
import time

from avatar2.targets import Target, TargetStates
from avatar2.protocols.inception import InceptionProtocol

class InceptionTarget(Target):
    def __init__(self, avatar, device_vendor_id="FFFF",
                 device_product_id="FFFF",
                 **kwargs):

        super(InceptionTarget, self).__init__(avatar, **kwargs)

        self._device_product_id = device_product_id
        self._device_vendor_id = device_vendor_id

    def init(self):
        inception = InceptionProtocol(self._device_vendor_id,
                                self._device_product_id,
                                output_directory=self.avatar.output_directory)

        if inception.connect():
            inception.reset()
            self.log.info("Connected to Target")
        else:
            self.log.warning("Connecting failed")
            return False

        self.update_state(TargetStates.STOPPED)

        self.protocols.set_all(inception)
        self.protocols.monitor = inception
