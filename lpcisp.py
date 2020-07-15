import binascii
import time
import enum
import serial

part_numbers = {
    0x1600F701: 'LPC2361',
    0x1600FF22: 'LPC2362',
    0x1600F902: 'LPC2364',
    0x1600E823: 'LPC2365',
    0x1600F923: 'LPC2366',
    0x1600E825: 'LPC2367',
    0x1600F925: 'LPC2368',
    0x1700E825: 'LPC2377',
    0x1700FD25: 'LPC2378',
    0x1700FF35: 'LPC2387',
    0x1800F935: 'LPC2387 (older)',
    0x1800FF35: 'LPC2388',
}


class ReturnCode(enum.Enum):
    CMD_SUCCESS = 0
    INVALID_COMMAND = 1
    SRC_ADDR_ERROR = 2
    DST_ADDR_ERROR = 3
    SRC_ADDR_NOT_MAPPED = 4
    DST_ADDR_NOT_MAPPED = 5
    COUNT_ERROR = 6
    INVALID_SECTOR = 7
    SECTOR_NOT_BLANK = 8
    SECTOR_NOT_PREP_WRITE_OP = 9
    COMPARE_ERROR = 10
    BUSY = 11
    PARAM_ERROR = 12
    ADDR_ERROR = 13
    ADDR_NOT_MAPPED = 14
    CMD_LOCKED = 15
    INVALID_CODE = 16
    INVALID_BAUD_RATE = 17
    INVALID_STOP_BIT = 18
    CODE_READ_PROTECTION_ENABLED = 19
    INVALID_FLASH_UNIT = 20
    USER_CODE_CHECKSUM = 21
    ERROR_SETTING_ACTIVE_PARTITION = 22


class ISP(object):
    def __init__(self, port, baud, stopbits=1, timeout=2.0, tgtclk=12000, sync_timeout=30.0):
        # Don't allow an infinite timeout, this class won't work if that is used
        assert timeout

        # Target clock must be > 10MHz
        assert int(tgtclk) >= 10000

        self._args = {
            'port': port,
            'baud': int(baud),
            'stopbits': int(stopbits),
            'timeout': int(timeout),
            'tgtclk': int(tgtclk),
            'sync_timeout': int(sync_timeout),
        }
        self._echo = True

        if self._args['stopbits'] == 2:
            ser_stopbits = serial.STOPBITS_TWO
        else:
            # default to 1 stop bit
            ser_stopbits = serial.STOPBITS_ONE

        s_args = {
            'port': self._args['port'],
            'baudrate': self._args['baud'],
            'stopbits': ser_stopbits,
            'timeout': self._args['timeout'],
        }
        self.s = serial.Serial(**s_args)
        self.synchronize()

    @property
    def echo(self):
        return self._echo

    @echo.setter
    def echo(self, mode):
        assert isinstance(mode, bool)
        response = self._echo_cmd(mode)
        if response == 'OK':
            self._echo = mode

    def reset(self, delay=0.5):
        self.s.dtr = True
        self.s.rts = True
        time.sleep(delay)
        self.s.dtr = False
        time.sleep(delay)

    def cancel_cmd(self):
        # Cancel the command to reduce weird debug states
        self.s.write(b'\x1b')
        # If echo is on read that one char back
        if self.echo:
            self.s.read(1)

    def cmd(self, cmd, return_code=True, lines=None, timeout=None):
        # Allow the default timeout to be overridden
        if timeout:
            self.s.timeout = timeout

        # Ensure command is bytes
        if not isinstance(cmd, bytes):
            cmd = cmd.encode()
            # If the command was not in bytes check if it needs \r\n appended
            if cmd[-2:] != b'\r\n':
                cmd += b'\r\n'

        self.s.write(cmd)
        response_lines = []

        # If echo is on the first response line may be an echo of the command
        if self.echo:
            response_lines.append(self.s.read_until())

            # If the line read does not match the command count it as one of the 
            # response lines
            if response_lines[0] != cmd:
                lines -= 1

        # If a return code is expected, read that now
        if return_code:
            response_lines.append(self.s.read_until())

        if lines is not None:
            # if there is a specific number of lines to receive, read them now
            response_lines.extend([self.s.read_until() for i in range(lines)])
        else:
            # Otherwise just read until the timeout is reached
            response_lines.extend(self.s.readlines())

        #print(f'{cmd} -> {response_lines}')

        # If the timeout was modified restore the default
        if timeout:
            self.s.timeout = self._args['timeout']

        # If echo is on the first response may be an echo of the command, drop 
        # that
        if len(response_lines) >= 1 and self.echo and response_lines[0] == cmd:
            response_lines = response_lines[1:]

        # If the response flag is set convert the next response line into the 
        # return code
        if len(response_lines) >= 1 and return_code:
            retcode = ReturnCode(int(response_lines[0]))
            if retcode != ReturnCode.CMD_SUCCESS:
                self.cancel_cmd()
                raise Exception(f'Command "{cmd}" Failed: {retcode}')
            response_lines = response_lines[1:]

        # convert from bytes to string and drop the \r\n
        converted_responses = [l[:-2].decode('latin-1') for l in response_lines]
        if not converted_responses:
            response = None
        elif len(converted_responses) == 1:
            response = converted_responses[0]
        else:
            response = converted_responses

        return response

    def synchronize(self):
        start = time.time()
        while True:
            now = time.time()
            if now - start > 10.0:
                raise Exception('Unable to synchronize!')

            self.reset()
            # Don't use self.cmd() because we don't want \r\n appended the sync 
            # byte
            response = self.cmd(b'?', return_code=False, lines=1)
            # Response is bytes because self.cmd() wasn't used
            if response != 'Synchronized':
                continue

            response = self.cmd('Synchronized', return_code=False, lines=1)
            if response != 'OK':
                continue

            response = self.cmd(f'{self._args["tgtclk"]}', return_code=False, lines=1)
            if response != 'OK':
                continue

            # success!
            break

    def unlock(self, code=23130):
        return self.cmd(f'U {code}')

    def set_baud_rate(self):
        return self.cmd(f'B {self._args["baud"]} {self._args["stopbits"]}')

    def _echo_cmd(self, mode):
        self.cmd('A 1')

    def write_to_ram(self, data, addr, size):
        raise NotImplementedError

    def _checksum(self, data):
        checksum = 0
        for b in data:
            checksum += b
            # 2 or 4-byte checksum?
            checksum &= 0xFFFFFFFF
        return checksum

    def uudecode(self, encoded):
        # The first char of the line is the length.  The ISP tends to repeat the 
        # last byte for padding which weirds out python so round the size of the 
        # line up to a multiple of 3.
        size = encoded[0] - 0x20
        pad = size % 3
        if pad:
            encoded = bytes([encoded[0] + (3 - pad)]) + encoded[1:]
        decoded = binascii.a2b_uu(encoded)

        # Now drop the padding bytes from the decoded data
        decoded = decoded[:size]
        #print(f'{encoded} -> {decoded}')
        return decoded

    def _read_data(self, size, timeout=60.0):
        #print(f'reading {size} bytes')
        # Override serial timeout
        self.s.timeout = None

        start = time.time()
        data = b''
        block_data = b''
        blocks = 0
        while len(data) < size:
            now = time.time()
            if now - start > timeout:
                self.cancel_cmd()
                raise Exception('Read data timeout!')

            line = self.s.read_until()
            #print(line)
            # See if this is a checksum line
            try:
                recvd_checksum = int(line)
                checksum = self._checksum(block_data)
                if checksum == recvd_checksum:
                    #print(f'BLOCK {blocks} OK ({checksum})')
                    self.cmd('OK', return_code=False, lines=0)
                    blocks += 1
                    data += block_data
                else:
                    #print(f'BLOCK {blocks} ERROR ({checksum})')
                    self.cmd('RESEND', return_code=False, lines=0)
                block_data = b''
            except ValueError:
                decoded = self.uudecode(line)
                block_data += decoded

        # restore the default timeout
        self.s.timeout = self._args['timeout']

        return data

    def read_memory(self, addr, size, timeout=60.0):
        # Ensure address is word-aligned
        assert addr % 4 == 0
        assert size % 4 == 0

        self.cmd(f'R {addr} {size}', lines=0)
        return self._read_data(size, timeout=timeout)

    def unprotect_sector(self, start_sector, end_sector=None):
        #if end_sector is None:
        #    end_sector = start_sector
        #assert end_sector >= start_sector
        #self.cmd(f'P {start_sector} {end_sector}')
        raise NotImplementedError

    def copy_ram_to_flash(self, flash_addr, ram_addr, size):
        # Ensure flash_addr is sector-aligned
        assert flash_addr % 256 == 0
        assert size in [256, 512, 1024, 4096]
        #self.cmd(f'C {flash_addr} {ram_addr} {size}')
        raise NotImplementedError

    def go(self, addr, mode='A'):
        assert addr % 4 == 0
        assert mode in ['A', 'T']
        return self.cmd(f'G {addr} {mode}')

    def erase_sectors(self, start_sector, end_sector=None):
        #if end_sector is None:
        #    end_sector = start_sector
        #assert end_sector >= start_sector
        #self.cmd(f'E {start_sector} {end_sector}')
        raise NotImplementedError

    def blank_check_sector(self, start_sector, end_sector=None):
        if end_sector is None:
            end_sector = start_sector
        assert end_sector >= start_sector
        self.cmd(f'I {start_sector} {end_sector}')

    def read_part_id(self, read_rev=False):
        part_response = self.cmd('J')

        try:
            part = part_numbers[int(part_response[1])]
        except KeyError:
            part = f'UNKNOWN ({part_response[1]})'

        if read_rev:
            #rev_bytes = self.read_memory(0x7FFFE070, 4)
            rev_bytes = self.read_memory(0x0007E070, 4)

            try:
                rev_val = int(rev_bytes)
                if rev_val == 0:
                    rev = '-'
                elif rev_val >= 1 and rev_val <= 26:
                    rev = 'A' + rev_val
                else:
                    rev = f'UNKNOWN ({rev_bytes.hex()})'
            except ValueError:
                rev = f'UNKNOWN ({rev_bytes.hex()})'

            return (part, rev)
        else:
            return part

    def read_boot_code_version(self):
        return self.cmd('K')

    def compare(self, addr1, addr2, size):
        self.cmd(f'M {addr1} {addr2} {size}')

