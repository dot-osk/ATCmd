
"""
负责串口交互，Modem交互

使用：

# 打开modem
s = ATModemCmd('COM9', 115200)
# 配置来电显示callback函数
s.notify_conf([CID_KEY_NUMBER], test_incoming_call)
s.callout('电话号码字符串')

来电显示callback函数接受一个参数，type: CIDData()。读取 CIDData.cid_number 即可获取来电显示号码

注意：使用了多线程，使用Python内置的SQLite需要注意。

# modem交互/调试方法
可以使用PuTTY等软件打开modem COM口， Windows为COMX，Linux为 /dev/ttyACMX 等
## 来电显示 CID 配置
设置区域 +GCI=B5，不然有的Modem不会显示CID信息（根据具体情况修改）
设置 +VCID=1， 显示格式化的信息，有些modem可能是其他命令
来电时的，CID信息在第一声铃声和第二声铃声之间，例如：

RING

DATE = 1120
TIME = 1748
NMBR = 186XXXXXXXX

RING

# 拨号
格式： ATD号码;
等待返回 OK
根据情况发送ATH命令挂机，不然影响通话

可选操作：在拨号前发送 ATH 强制挂机


需要：
 - python3.x
 - pyseiral

测试平台： python3.6 x64, pyserial??, Windows 10

"""


from serial import Serial
import logging
import re
import threading
from time import sleep

# 附加到每条发送的AT指令结尾的换行，AT响应的每行结尾
ATCMD_EOL = '\r\n'
# 来电显示响应
CID_KEY_NUMBER = 'NMBR'
CID_KEY_NAME = 'NAME'
CID_KEY_DATE = 'DATE'
CID_KEY_TIME = 'TIME'

# 用于匹配来电显示信息的RE
_CID_RE = r'(?P<CID_KEY>(({})|({})|({})|({})))\s*=\s*(?P<CID_VALUE>.*)'\
    .format(CID_KEY_NAME, CID_KEY_NUMBER, CID_KEY_DATE, CID_KEY_TIME)

# 空闲状态时读取串口的超时时间，None为一直等待新的EOL
TIMEOUT_IDLE = None
# 有来电等状态时读取串口的超时时间，秒
TIMEOUT_RING = 10


class CIDData(dict):
    """保存CID（来电显示）信息，方便读取号码等"""
    def __init__(self):
        super(CIDData, self).__init__()
        self.clear_cid()
        
    def clear_cid(self):
        """ 清空已保存的cid信息"""
        self[CID_KEY_NUMBER] = ''
        self[CID_KEY_NAME] = ''
        self[CID_KEY_DATE] = ''
        self[CID_KEY_TIME] = ''
    
    @property
    def cid_number(self):
        return self.get(CID_KEY_NUMBER)
    
    @property
    def cid_date(self):
        return self.get(CID_KEY_DATE)

    @property
    def cid_time(self):
        return self.get(CID_KEY_TIME)

    @property
    def cid_name(self):
        return self.get(CID_KEY_NAME)


class ATModemCmd(object):
    """打开modem, 和modem交互"""
    def __init__(self, serial_port: str, serial_baud_rate: int):
        self.__logger = logging.getLogger('ATModemCmd')
        
        # AT 指令的响应
        self.cmd_resp = ''
        # 来电显示信息
        self.cid_data = CIDData()
        # 至少需要收到以下CID信息才调用指定的callback
        self.cid_notify_required_key = [CID_KEY_NUMBER]
        # 接受完CID信息后的callback函数
        self._cid_notify_command = None

        # 打开串口
        try:
            self.ser = Serial(serial_port, serial_baud_rate, timeout=TIMEOUT_RING)
            self.__logger.debug('Open {},{}'.format(serial_port, serial_baud_rate))
        except Exception as err:
            self.ser = None
            self.__logger.error('Failed to open {},{}:{}'.format(serial_port, serial_baud_rate, err))
        # 初始化modem，开始modem response监听线程
        if self.ser:
            self.__init_modem()
            threading.Thread(target=self.__modem_response, daemon=True).start()

    def __clear_cid(self):
        """
        清空cid信息
        :return:
        """
        self.__logger.debug('clear stored CID data')
        self.cid_data.clear_cid()

    def notify_conf(self, cid_required_key, notify_command):
        """
        配置来电通知, notify_command() 必须接收一个参数，传递的参数是CIDData().
        当来电信息满足 cid_field_required 指定的项目后， 调用 notify_command
        :param cid_required_key: list(), 可选 DATE, TIME, NMBR, NAME
        :param notify_command: cid callback 函数/方法
        :return:
        """
        cid_key = []
        
        # 检查传入的参数: Key
        for i in cid_required_key:
            if i in [CID_KEY_NUMBER, CID_KEY_NAME, CID_KEY_DATE, CID_KEY_TIME]:
                cid_key.append(i)
            else:
                # 指定的CID Key无效，忽略
                self.__logger.warning('CID key {} invalid, ignore.'.format(i))
        
        self.cid_notify_required_key = cid_key
        
        if callable(notify_command):
            self._cid_notify_command = notify_command
        else:
            self._cid_notify_command = logging.warning
            self.__logger.warning('{} is not callable, use logging.warning instead.', type(notify_command))

    def set_read_timeout(self, timeout):
        """
        设置串口的readline() 超时时间
        :param timeout:
        :return:
        """
        self.__logger.debug('set serial readline() timeout to {} ({})'.format(timeout, type(timeout)))
        self.ser.timeout = timeout

    def __init_modem(self):
        """
        todo: 测试串口是否连接了AT指令设备
        初始化 modem
        :return:
        """
        self.__logger.debug('initialization modem...')
        self.send_cmd('ATZ')
        self.send_cmd('ATE0')
        self.send_cmd('AT+GCI=B5')
        self.send_cmd('AT+VCID=1')

    def close(self):
        """
        重置modem, 关闭串口
        todo: close() 串口后，__modem_response() 会抛出异常
        :return:
        """
        if self.ser:
            self.__logger.debug('Close session.')
            self.send_cmd('ATZ')
            self.ser.close()

    def send_cmd(self, cmd: str):
        """
        向modem发送命令
        :param cmd:
        :return:
        """
        cmd += ATCMD_EOL
        if self.ser:
            self.ser.write(cmd.encode('utf-8'))
            self.__logger.debug('send cmd: {}'.format(repr(cmd)))
        else:
            self.__logger.error('cannot send cmd: {} , Serial port not opened'.format(repr(cmd)))

    def callout(self, number: str, hung_time=10):
        """
        拨打电话
        :param number:
        :param hung_time: 最大允许的modem挂机前等待
        :return:
        """
        number = number.strip()
        if number == '':
            self.__logger.warning('Call empty number, cancelled')
            return
        # 强制挂机
        self.send_cmd('ATH')
        sleep(1)
        self.cmd_resp = ''
        self.send_cmd('ATD{};'.format(number))
        # 检测拨号命令超时
        call_second = 0
        while self.cmd_resp == '':
            sleep(1)
            call_second += 1
            if call_second > hung_time:
                self.__logger.info('call {} timeout'.format(number))
                break
        self.__logger.info('call {} done, modem response:{}'.format(number, self.cmd_resp))
        self.send_cmd('ATH')

    def __modem_response(self):
        """
        接收并处理从串口接收到的数据
        :return:
        """
        while self.ser:
            # 接收数据
            self.__logger.debug('waiting for incoming data, timeout is {}({})'.
                                format(self.ser.timeout, type(self.ser.timeout)))
            # 等待串口接收到EOL
            resp = self.ser.readline()
            resp = resp.decode()

            self.__logger.debug('serial port received: {}'.format(repr(resp)))
            # 超时收到空内容
            if resp == '':
                self.set_read_timeout(TIMEOUT_IDLE)
                self.cmd_resp = ''
                self.__clear_cid()
                continue

            # 根据当前的状态处理收到的数据
            resp = resp.strip(ATCMD_EOL)
            if resp == '':
                # CID 信息中会包含空行，直接忽略
                self.set_read_timeout(TIMEOUT_RING)
                continue

            # 收到 OK, ERROR,
            if resp in ['OK', 'ERROR', 'NO CARRIER']:
                self.__logger.debug('get cmd response')
                # 命令执行结果
                self.cmd_resp = resp
                self.set_read_timeout(TIMEOUT_IDLE)
                self.__clear_cid()
                continue

            # 有来电
            if resp in ['RING']:
                self.__logger.debug('get incoming ring')
                self.set_read_timeout(TIMEOUT_RING)
                self.cmd_resp = ''
                continue

            # 处理CID信息
            match_ = re.match(_CID_RE, resp)
            if match_:
                cid_ = match_.groupdict()
                cid_key = cid_.get('CID_KEY', ' ')
                cid_value = cid_.get('CID_VALUE', '')
                # 保存收到的CID信息
                self.cid_data[cid_key] = cid_value
                self.__logger.debug('get CID data:{}:{}'.format(cid_key, cid_value))
                self.__check_cid_notify()

                self.cmd_resp = ''
                self.set_read_timeout(TIMEOUT_RING)
                continue

            # 其他未知命令
            self.__logger.warning('unknown response: {}'.format(resp))
            self.cmd_resp = resp
            self.set_read_timeout(TIMEOUT_IDLE)

    def __check_cid_notify(self):
        """
        检测是否满足通知的条件，CID信息是否获取够了
        :return:
        """
        for i in self.cid_notify_required_key:
            if self.cid_data.get(i, '') == '':
                # 如果有一个CID属性没有获取到或者为空则表示信息没有获取完整
                self.__logger.debug('check cid: still need {} data'.format(i))
                return
        # 获取到了需要的信息, 调用callback函数
        self._cid_notify_command(self.cid_data)
        self.__clear_cid()


if __name__ == '__main__':
    def test_incoming_call(cid):
        print('incoming call {}'.format(cid.cid_number))

    LOGGING_FORMAT = "[%(filename)s:%(lineno)s-%(funcName)s()] %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=LOGGING_FORMAT)

    s = ATModemCmd('COM9', 115200)
    s.notify_conf([CID_KEY_NUMBER], test_incoming_call)
