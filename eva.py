import argparse
import bisect
import canopen
import json
import logging
import os.path
import signal
import sys
import time
import traceback
from canopen import nmt
from collections import OrderedDict
from display import DisplayApp
from enum import Enum
from threading import Thread


class ForceMapping(object):
    def __init__(self):
        self._map = dict([(0, 0), (50, 5826), (60, 6783), (70, 7209), (80, 8177), (90, 8816), (100, 9498), (130, 11469)])
        self._reverse = self.reverse(self._map)

    def configure(self, key, value):
        if key in self._map:
            self._map[key] = value
        else:
            raise Exception('No such key ' + key)
        self._reverse = self.reverse(self._map)

    def get(self, key):
        return self._map[key]

    def write(self):
        with open("mapping.json", "w") as file:
            # TODO catch write issues
            json.dump(self._map, file)

    def read(self):
        if os.path.isfile("mapping.json"):
            with open("mapping.json", "r") as file:
                # TODO catch read problem
                self._map = json.load(file)
            for key in self._map:
                self._map[int(key)] = self._map.pop(key)
            self._reverse = self.reverse(self._map)

    def reverse(self, omap):
        return OrderedDict(sorted([(t[1], t[0]) for t in omap.items()], key=lambda t: t[0]))

    def map(self, value):
        if value in self._reverse:
            return self._reverse[value]
        length = len(self._reverse)
        pos = bisect.bisect_left(self._reverse.keys(), value)
        if length == pos:
            pos = length - 1

        elif 0 == pos:
            pos = 1
        key1 = self._reverse.keys()[pos-1]
        key2 = self._reverse.keys()[pos]
        value1 = self._reverse[key1]
        value2 = self._reverse[key2]
        pitch = float(value2 - value1) / float(key2 - key1)
        retval = pitch * (value - key1) + value1
        return int(retval)


class State(Enum):
    OFFLINE = 0
    INIT = 1
    ONLINE = 2


# TODO daemon goes into STOPPED state. Resolve STOPPED state. Use fast writing to cause STOPPED state.
class Eva(object):
    def __init__(self):
        self._PDO = True
        self._mapping = ForceMapping()
        self._display = None
        self._run = True
        self._state = State.OFFLINE
        self._network = None
        self._controller = None
        self._main_thread = Thread(target=self.mainloop)
        self._read = False
        self._read_thread = None
        self._monitor_thread = None
        self._heartbeat = False

    def start(self, args):
        self._mapping.read()
        self._display = DisplayApp(args.d, self._mapping)
        self._network = canopen.Network()
        self._network.connect(bustype='socketcan', channel=args.dev)
        self._controller = self._network.add_node(7, 'CANopenSocket.eds')
        # main EVA thread here
        self._main_thread.start()
        # blocks until the UI ends
        try:
            self._display.run()
        except BaseException as e:
            logging.error(traceback.format_exc())

    def stop(self):
        self._run = False
        self._read = False
        self._mapping.write()
        if self._monitor_thread:
            self._monitor_thread.join()
            self._monitor_thread = None
        if self._read_thread:
            self._read_thread.join()
            self._read_thread = None
        if self._main_thread:
            self._main_thread.join()
            self._main_thread = None
        if self._controller:
            self._controller.pdo.tx[1].stop()
            self._controller.nmt.state = 'STOPPED'
            self._controller = None
        if self._network:
            self._network.disconnect()
            self._network = None
        if self._display:
            self._display.stop()
            self._display = None

    def mainloop(self):
        next_state = State.OFFLINE
        while self._run:
            #print('%s' % self._state)
            if State.OFFLINE == self._state:
                next_state = self.offline()
            if State.INIT == self._state:
                next_state = self.init()
            if State.ONLINE == self._state:
                next_state = self.online()
            self._state = next_state

    def offline(self):
        if not self._PDO:
            if self._read:
                self._read = False
                print('Stop')
                self._read_thread.join()
                self._read_thread = None
        self.connected(False)
        if self._monitor_thread:
            self._monitor_thread.join()
            self._monitor_thread = None
        nmt_state = None
        try:
            self._controller.nmt.state = 'PRE-OPERATIONAL'
            self._controller.sdo['Producer heartbeat time'].raw = 50
        except canopen.sdo.SdoCommunicationError as e:
            logging.info('Failed to configure heartbeat.')
        except BaseException as e:
            logging.error(traceback.format_exc())
        try:
            nmt_state = self._controller.nmt.wait_for_heartbeat(0.1)
        except canopen.nmt.NmtError as e:
            pass
        if nmt_state:
            self.connected(True)
            return State.INIT
        return State.OFFLINE

    def init(self):
        # TODO somewhere here SDO timeouts may occur.
        self._controller.nmt.state = 'PRE-OPERATIONAL'
        try:
            self._controller.sdo['Producer heartbeat time'].raw = 50
        except canopen.sdo.SdoCommunicationError as e:
            logging.info('Failed to configure heartbeat.')
        if self._PDO:
            self._controller.pdo.read()
            self._controller.pdo.tx[1].clear()
            # TODO replace with Throttle_Command 0x3216, subindex 0 length 2 readonly
            self._controller.pdo.tx[1].add_variable(0x2110, 1)
            # Asynchronous PDO. If one process variable changes, the data is transfered.
            self._controller.pdo.tx[1].trans_type = 254
            # Transmit at least every 1000 milliseconds.
            self._controller.pdo.tx[1].event_timer = 1000
            self._controller.pdo.tx[1].enabled = True
            self._controller.pdo.save()
            self._controller.pdo.tx[1].add_callback(callback=self.received)
        else:
            if not self._read:
                self._read = True
                print('Start')
                self._read_thread = Thread(target=self.read)
                self._read_thread.start()
        # TODO With the initialisation problem the emulator will not go back into operational mode and we get no data.
        self._controller.nmt.state = 'OPERATIONAL'
        if self._monitor_thread:
            print('Monitor thread not gone')
        else:
            self._monitor_thread = Thread(target=self.monitor_heartbeat)
            self._monitor_thread.start()
        return State.ONLINE

    def read(self):
        while self._read:
            try:
                value = self._controller.sdo[0x3216].raw
                self.show_data(value)
            except canopen.sdo.SdoError as e:
                print('Reading Throttle_Command failed')
            time.sleep(0.1)

    def online(self):
        time.sleep(0.1)
        if self._heartbeat:
            return State.ONLINE
        else:
            return State.OFFLINE

    def received(self, message):
        for var in message:
            self.show_data(var.raw)

    def show_data(self, value):
        logging.debug('Throttle_Command: ' + str(value))
        if self._display:
            self._display.set_measure(value)
            self._display.set_torque(self._mapping.map(value))

    def monitor_heartbeat(self):
        while self._run:
            nmt_state = None
            try:
                nmt_state = self._controller.nmt.wait_for_heartbeat(0.2)
            except canopen.nmt.NmtError as e:
                pass
            if nmt_state:
                self.connected(True)
            else:
                self.connected(False)
                break

    def connected(self, connected):
        if self._display:
            self._display.connected(connected)
        self._heartbeat = connected


eva = Eva()


def handler(signum, frame):
    eva.stop()


def main():
    signal.signal(signal.SIGINT, handler)
    parser = argparse.ArgumentParser(description='EVA')
    parser.add_argument('dev', metavar='<CAN device name>', help='CAN device name')
    parser.add_argument('-i', default=42, type=int, choices=range(1, 127), required=False, help='canopen Node ID')
    parser.add_argument('-d', action="store_true")
    args, left = parser.parse_known_args()
    sys.argv = sys.argv[:1] + left

    logging.basicConfig()
    some_logger = logging.getLogger('canopen.network')
    some_logger.setLevel(logging.DEBUG)
    some_logger.addHandler(logging.StreamHandler())

    eva.start(args)
    eva.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
