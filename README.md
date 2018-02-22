# ATCmd

AT modem来电显示和拨号demo.

负责串口交互，Modem交互，modem串口号可以在Windows设备管理器 → 调制解调器 → XXX modem → “调制解调器”选项卡 中查看COM号

使用：

```python
# 打开modem
s = ATModemCmd('COM9', 115200)
# 配置来电显示callback函数
s.notify_conf([CID_KEY_NUMBER], test_incoming_call)
s.callout('电话号码字符串')
```

来电显示callback函数接受一个参数，type: CIDData()。读取 CIDData.cid_number 即可获取来电显示号码


来电显示测试log

![GUI](https://github.com/dot-osk/ATCmd/raw/master/doc/res/at-in.PNG)


拨号测试log

![GUI](https://github.com/dot-osk/ATCmd/raw/master/doc/res/at-out.PNG)



注意：使用了多线程，使用Python内置的SQLite需要注意。

# modem交互/调试方法

可以使用PuTTY等软件打开modem COM口， Windows为COMX，Linux为 /dev/ttyACMX 等

## 来电显示 CID 配置

设置区域 +GCI=B5，不然有的Modem不会显示CID信息（根据具体情况修改）

设置 +VCID=1， 显示格式化的信息，有些modem可能是其他命令

来电时的，CID信息在第一声铃声和第二声铃声之间，例如：

```text
RING

DATE = 1120
TIME = 1748
NMBR = 186XXXXXXXX

RING
```

## 拨号

格式： ATD号码;

等待返回 OK

根据情况发送ATH命令挂机，不然影响通话

可选操作：在拨号前发送 ATH 强制挂机



# 需要

 - python3.x
 - pyseiral

测试平台： python3.6 x64, pyserial??, Windows 10


