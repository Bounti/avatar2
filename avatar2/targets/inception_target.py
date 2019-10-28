import sys

if sys.version_info < (3, 0):
    from Queue import PriorityQueue
else:
    from queue import PriorityQueue
import time

from avatar2.targets import Target, TargetStates
from avatar2.protocols.inception import InceptionProtocol

from ..watchmen import watch

class InceptionTarget(Target):
    def __init__(self, avatar, device_vendor_id=0x04b4,
                 device_product_id=0x00f1,
                 **kwargs):

        super(InceptionTarget, self).__init__(avatar, **kwargs)

        self._device_product_id = device_product_id
        self._device_vendor_id = device_vendor_id

    @watch('TargetInit')
    def init(self):
        inception = InceptionProtocol(device_vendor_id=self._device_vendor_id,
                                device_product_id=self._device_product_id,
                                output_directory=self.avatar.output_directory)

        if inception.connect():
            inception.reset()
            self.update_state(TargetStates.RUNNING)
            self.log.info("Connected to Target")
        else:
            self.log.warning("Connecting failed")
            return False

        if inception.stop():
          self.update_state(TargetStates.STOPPED)

        self.protocols.set_all(inception)
        self.protocols.monitor = inception 
        
        self.wait()

    def reset(self, halt=True):
        self.protocols.execution.reset(halt=halt)

