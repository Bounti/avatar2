# usb.bus_id == 3 and usb.device_address == 55
import sys
import subprocess
import telnetlib
import logging
import distutils
import array

import binascii
import struct
import ctypes

from avatar2.targets import TargetStates, Target
from avatar2.message import AvatarMessage, UpdateStateMessage, BreakpointHitMessage

# Python USB package to deal with Inception-debugger.
# I choose that one because it's user-friendly.
# I am not aware of the performance and difference with other.
# Any update to a better package will be appreciate.
import usb.core
import usb.util

from os.path import abspath
if sys.version_info < (3, 0):
    import Queue as queue
else:
    import queue

END_OF_MSG = b'\r\n\r>'

class InceptionProtocol(object):
    """
    This class implements the Inception protocol.
    It enables communication with the Inception-debugger hardware.

    :param additional_args:    Additional arguments delivered to Inception.
    :type  additional_args:    list
    :param device_vendor_id:           The usb device id to connect to.
    :type  device_vendor_id:           int
    :param device_product_id:          The usb device id to connect to.
    :type  device_product_id:          int
    """

    def __init__(self, additional_args=[], device_vendor_id=0x04b4,
                 device_product_id=0x00f1,
                 origin=None,
                 output_directory='/tmp'):

        # USB device information
        self._device_vendor_id = device_vendor_id
        self._device_product_id = device_product_id
        self._device = None

        # USB device handler
        self._ep_out = None
        self._ep_in_response = None
        self._ep_in_irq = None

        # internal variables
        self._bkpt_limit = 0
        self._bkpt_list = [None] * 1
        self._debug_enabled = False

        # avatar2 related variables
        self._origin = origin
        self.log = logging.getLogger('%s.%s' %
                                     (origin.log.name, self.__class__.__name__)
                                     ) if origin else \
            logging.getLogger(self.__class__.__name__)

    def connect(self):
        """
        Connects to USB3 Inception-debugger for all subsequent communication
        returns: True on success, else False
        """

        self._device = usb.core.find(idVendor=self._device_vendor_id,
                idProduct=self._device_product_id)

        if self._device is None:
            self.log.error('Failed to connect to Inception-debugger')
            raise ConnectionRefusedError("Inception-debugger is not connected")

        self._device.reset();

        self._device.set_configuration()

        # # get an endpoint instance
        # cfg = self._device.get_active_configuration()
        # intf = cfg[(0,0)]
        intf = self._device[0][(0,0)]

        self._ep_out = usb.util.find_descriptor(intf, bEndpointAddress=0x01)

        self._ep_in_response = usb.util.find_descriptor(intf, bEndpointAddress=0x81)

        self._ep_in_irq = usb.util.find_descriptor(intf, bEndpointAddress=0x82)

        if self._ep_out is None:
            raise ConnectionRefusedError("Inception-debugger is connected but no endpoint 0x01 found")
        if self._ep_in_response is None:
            raise ConnectionRefusedError("Inception-debugger is connected but no endpoint 0x81 found")
        if self._ep_in_irq is None:
            raise ConnectionRefusedError("Inception-debugger is connected but no endpoint 0x82 found")

        UpdateStateMessage(self, TargetStates.INITIALIZED)

        return True


    def reset(self):
        """
        Resets the target
        returns: True on success, else False
        """
        data = '3000000030000000'

        # adata = utils.to_array(data)
        # length = utils.data_len(data)
        # buff = usb.util.create_buffer(length)

        # self._ep_out.write(''.join('{:02x}'.format(x) for x in data))
        self._ep_out.write(bytearray.fromhex(data))

        # Now we need to retrive the number of supporter hw bkpt from the core
        res = self.read_memory(0xE0002000, 4)
        FP_CTRL = struct.unpack_from("I", res, 0)[0]

        # bit [11:8] are the number of supported comparators
        self._bkpt_limit = (FP_CTRL >> 8) & 0xF
        self.log.debug(("Number of available breakpoints %d") % (self._bkpt_limit))
        print(("Number of available breakpoints %d") % (self._bkpt_limit))

        # bkpt list contains status of hw bkpt (enabled/disabled)
        self._bkpt_list = [0] * self._bkpt_limit

        # enable the FlashPatch module : breakpoint
        # FlashPatch Control Register (FP_CTRL)
        self.write_memory(0xE0002000, 4, 1)

        return True

    def shutdown(self):
        """
        Shuts down Inception
        returns: True on success, else False
        """
        usb.util.dispose_resources(self._device)

        return True

    def cont(self):
        """
        Continues the execution of the target
        :returns: True on success
        """
        self.write_memory(0xE000EDF0, 4, (0xA05F << 16) | (0<<1) | (1 << 0))

        self._debug_enabled = False
        return True

    def stop(self):
        """
        Stops the execution of the target
        """
        write_memory(self, 0xE0002000, 4, (0xA05F << 16) | (1<<1) | (1 << 0))

        self._debug_enabled = False
        return True

    def step(self):
        """
        Steps one instruction
        """
        if not self._debug_enabled:
            # Enable Debug mode if not activated
            self.write_memory(0xE000EDF0, 4, (0xA05F << 16) | (1 << 2))
            self._debug_enabled = True

        # Execute a step
        self.write_memory(0xE000EDF0, 4, (0xA05F << 16) | (1 << 2))

        return ret

    def write_memory(self, address, size, value, num_words=1, raw=False):
        """
        Writing to memory of the target

        :param address:   The address from where the memory-write should
                          start
        :param size:      The size of the memory write
        :param value:     The actual value written to memory
        :type val:        int if num_words == 1 and raw == False
                          list if num_words > 1 and raw == False
                          str or byte if raw == True
        :param num_words: The amount of words to read
        :param raw:       Specifies whether to write in raw or word mode
        :returns:         True on success else False
        """

        command = 0x14000001

        # USB data containing the write order header (without data)
        data = ctypes.create_string_buffer(12)

        # Top level command
        struct.pack_into(">i", data, 0, command)

        if size <= 4:
            struct.pack_into(">I", data, 4, address)
            struct.pack_into(">I", data, 8, value)
            self._ep_out.write(data)
        else:
            i = 0
            while i < size:
                packet = data

                struct.pack_into(">I", data, 4, address+ (4*i))

                struct.pack_into(">c", data, 8, value[0+i].encode())
                struct.pack_into(">c", data, 9, value[1+i].encode())
                struct.pack_into(">c", data, 10, value[2+i].encode())
                struct.pack_into(">c", data, 11, value[3+i].encode())

                # print("Sending packet from "+str(i)+" to "+str(i+4))
                # for field in data:
                #     print(field)

                self._ep_out.write(packet)

                i = i + 4
        return True

    def read_memory(self, address, size, words=1, raw=False):
        """
        Reading from memory of the target

        :param address:     The address to read from
        :param size:        The size of a read word
        :param words:       The amount of words to read (default: 1)
        :param raw:         Whether the read memory is returned unprocessed
        :return:          The read memory
        """

        command = 0x24000001

        # USB data containing the write order header (without data)
        data = ctypes.create_string_buffer(8)

        # Top level command
        struct.pack_into(">I", data, 0, command)

        result = ctypes.create_string_buffer(size)

        i = 0
        while i < size:
                packet = data

                struct.pack_into(">I", packet, 4, address+ (4*i))

                self._ep_out.write(data)

                message = self._ep_in_response.read(50, 0)

                # print(message)

                # message is a bitstream of 64bits integer.
                # The highest 32bits are the status code
                if message[3] != 2:
                    raise Error("Debugger returned an error")

                value = message[4] << 24
                value = value | message[5] << 16
                value = value | message[6] << 8
                value = value | message[7]

                struct.pack_into(">I", result, i, value)
                i = i + 4

        if raw:
            return result.raw
        else:
            return result

    def write_register(self, register, value):
        """
        Writing a register to the target

        :param register:     The name of the register
        :param value:        The actual value written to the register
        """
        self.write_memory(0xE000EDF8, 4, value)

        self.write_memory(0xE000EDF4, 4, (reg |  (1 << 16)) )

        return True

    def read_register(self, register):
        """
        Reading a register from the target

        :param register:     The name of the register
        :return:             The actual value read from the register
        """
        self.write_memory(0xE000EDF4, 4, register)

        return self.read_memory(0xE000EDF8, 4)

    def set_breakpoint(self, line, hardware=False, temporary=False, regex=False,
                       condition=None, ignore_count=0, thread=0, **kwargs):
        """Inserts a breakpoint

        :param bool hardware: Hardware breakpoint
        :param bool tempory:  Tempory breakpoint
        :param str regex:     If set, inserts breakpoints matching the regex
        :param str condition: If set, inserts a breakpoint with the condition
        :param int ignore_count: Amount of times the bp should be ignored
        :param int thread:    Threadno in which this breakpoints should be added
        """
        # Update bkpt counter and update bkpt register address
        indexes = [i for i, j in enumerate(self._bkpt_list) if j == 0]

        # If no bkpt are available, raise an exception
        if indexes is None:
            raise Exception("Breakpoint limitation reaches")

        # Compute a free comparator register address
        FPCRegAddress = 0xE0002008 + ( indexes[0] * 4 )

        #set the flash patch comparator register value (FP_COMPx)
        FPCRegValue = b'0'
        FPCRegValue += b'0x11' << 30 # Breakpoint on match
        FPCRegValue += address << 2 # Address to compare against
        FPCRegValue += b'0x11' # Enable the comparator

        self.write_memory(FPCRegAddress, 4, FPCRegValue)

        return True

    def set_watchpoint(self, variable, write=True, read=False):
        """Inserts a watchpoint

        :param      variable: The name of a variable or an address to watch
        :param bool write:    Write watchpoint
        :param bool read:     Read watchpoint
        """
        return True

    def remove_breakpoint(self, bkptno):
        """Deletes a breakpoint"""

        if self._bkpt_limit < bkptno :
            raise Execption("bkptno higher than supported breakpoint")

        # Update bkpt counter and update bkpt register address
        FPCRegAddress = 0xE0002008 + ( bkptno * 4 )

        #set the flash patch comparator register value (FP_COMPx)
        FPCRegValue += b'0x00' # Enable the comparator

        write_memory(self, FPCRegAddress, 4, FPCRegValue)

        self._bkpt_list[bkptno] = 0

        return True
