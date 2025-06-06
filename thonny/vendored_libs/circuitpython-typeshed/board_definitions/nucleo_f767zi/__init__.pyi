# SPDX-FileCopyrightText: 2024 Justin Myers
#
# SPDX-License-Identifier: MIT
"""
Board stub for NUCLEO STM32F767
 - port: stm
 - board_id: nucleo_f767zi
 - NVM size: Unknown
 - Included modules: _asyncio, _bleio, _pixelmap, adafruit_bus_device, adafruit_pixelbuf, aesio, array, atexit, binascii, bitbangio, bitmapfilter, bitmaptools, board, builtins, builtins.pow3, busdisplay, busio, busio.SPI, busio.UART, codeop, collections, digitalio, displayio, epaperdisplay, errno, fontio, fourwire, framebufferio, getpass, gifio, i2cdisplaybus, io, jpegio, json, keypad, keypad.KeyMatrix, keypad.Keys, keypad.ShiftRegisterKeys, keypad_demux, keypad_demux.DemuxKeyMatrix, locale, math, microcontroller, msgpack, onewireio, os, os.getenv, pulseio, pwmio, rainbowio, random, re, rtc, sdcardio, select, sharpdisplay, storage, struct, supervisor, sys, terminalio, tilepalettemapper, time, touchio, traceback, ulab, usb_cdc, usb_hid, usb_midi, vectorio, warnings, zlib
 - Frozen libraries: 
"""

# Imports
import microcontroller


# Board Info:
board_id: str


# Pins:
A0: microcontroller.Pin  # PA03
A1: microcontroller.Pin  # PC00
A2: microcontroller.Pin  # PC03
A3: microcontroller.Pin  # PF03
A4: microcontroller.Pin  # PF05
A5: microcontroller.Pin  # PF10
A6: microcontroller.Pin  # PB01
A7: microcontroller.Pin  # PC02
A8: microcontroller.Pin  # PF04
D0: microcontroller.Pin  # PG09
D1: microcontroller.Pin  # PG14
D2: microcontroller.Pin  # PF15
D3: microcontroller.Pin  # PE13
D4: microcontroller.Pin  # PF14
D5: microcontroller.Pin  # PE11
D6: microcontroller.Pin  # PE09
D7: microcontroller.Pin  # PF13
D8: microcontroller.Pin  # PF12
D9: microcontroller.Pin  # PD15
D10: microcontroller.Pin  # PD14
D11: microcontroller.Pin  # PA07
D12: microcontroller.Pin  # PA06
D13: microcontroller.Pin  # PA05
D14: microcontroller.Pin  # PB09
D15: microcontroller.Pin  # PB08
D16: microcontroller.Pin  # PC06
D17: microcontroller.Pin  # PB15
D18: microcontroller.Pin  # PB13
D19: microcontroller.Pin  # PB12
D20: microcontroller.Pin  # PA15
D21: microcontroller.Pin  # PC07
D22: microcontroller.Pin  # PB05
D23: microcontroller.Pin  # PB03
D24: microcontroller.Pin  # PA04
D25: microcontroller.Pin  # PB04
D26: microcontroller.Pin  # PB06
D27: microcontroller.Pin  # PB02
D28: microcontroller.Pin  # PD13
D29: microcontroller.Pin  # PD12
D30: microcontroller.Pin  # PD11
D31: microcontroller.Pin  # PE02
D32: microcontroller.Pin  # PA00
D33: microcontroller.Pin  # PB00
D34: microcontroller.Pin  # PE00
D35: microcontroller.Pin  # PB11
D36: microcontroller.Pin  # PB10
D37: microcontroller.Pin  # PE15
D38: microcontroller.Pin  # PE14
D39: microcontroller.Pin  # PE12
D40: microcontroller.Pin  # PE10
D41: microcontroller.Pin  # PE07
D42: microcontroller.Pin  # PE08
D43: microcontroller.Pin  # PC08
D44: microcontroller.Pin  # PC09
D45: microcontroller.Pin  # PC10
D46: microcontroller.Pin  # PC11
D47: microcontroller.Pin  # PC12
D48: microcontroller.Pin  # PD02
D49: microcontroller.Pin  # PG02
D50: microcontroller.Pin  # PG03
D51: microcontroller.Pin  # PD07
D52: microcontroller.Pin  # PD06
D53: microcontroller.Pin  # PD05
D54: microcontroller.Pin  # PD04
D55: microcontroller.Pin  # PD03
D56: microcontroller.Pin  # PE02
D57: microcontroller.Pin  # PE04
D58: microcontroller.Pin  # PE05
D59: microcontroller.Pin  # PE06
D60: microcontroller.Pin  # PE03
D61: microcontroller.Pin  # PF08
D62: microcontroller.Pin  # PF07
D63: microcontroller.Pin  # PF09
D64: microcontroller.Pin  # PG01
D65: microcontroller.Pin  # PG00
D66: microcontroller.Pin  # PD01
D67: microcontroller.Pin  # PD00
D68: microcontroller.Pin  # PF00
D69: microcontroller.Pin  # PF01
D70: microcontroller.Pin  # PF02
D71: microcontroller.Pin  # PA07
DAC1: microcontroller.Pin  # PA04
DAC2: microcontroller.Pin  # PA05
LED1: microcontroller.Pin  # PB00
LED2: microcontroller.Pin  # PB07
LED3: microcontroller.Pin  # PB14
SW: microcontroller.Pin  # PC13
SD_D0: microcontroller.Pin  # PC08
SD_D1: microcontroller.Pin  # PC09
SD_D2: microcontroller.Pin  # PC10
SD_D3: microcontroller.Pin  # PC11
SD_CMD: microcontroller.Pin  # PD02
SD_CK: microcontroller.Pin  # PC12
SD_SW: microcontroller.Pin  # PG02
OTG_FS_POWER: microcontroller.Pin  # PG06
OTG_FS_OVER_CURRENT: microcontroller.Pin  # PG07
USB_VBUS: microcontroller.Pin  # PA09
USB_ID: microcontroller.Pin  # PA10
USB_DM: microcontroller.Pin  # PA11
USB_DP: microcontroller.Pin  # PA12
UART2_TX: microcontroller.Pin  # PD05
UART2_RX: microcontroller.Pin  # PD06
UART2_RTS: microcontroller.Pin  # PD04
UART2_CTS: microcontroller.Pin  # PD03
VCP_TX: microcontroller.Pin  # PD08
VCP_RX: microcontroller.Pin  # PD09
UART3_TX: microcontroller.Pin  # PD08
UART3_RX: microcontroller.Pin  # PD09
UART5_TX: microcontroller.Pin  # PB06
UART5_RX: microcontroller.Pin  # PB12
UART6_TX: microcontroller.Pin  # PC06
UART6_RX: microcontroller.Pin  # PC07
UART7_TX: microcontroller.Pin  # PF07
UART7_RX: microcontroller.Pin  # PF06
UART8_TX: microcontroller.Pin  # PE01
UART8_RX: microcontroller.Pin  # PE00
SPI3_NSS: microcontroller.Pin  # PA04
SPI3_SCK: microcontroller.Pin  # PB03
SPI3_MISO: microcontroller.Pin  # PB04
SPI3_MOSI: microcontroller.Pin  # PB05
I2C1_SDA: microcontroller.Pin  # PB09
I2C1_SCL: microcontroller.Pin  # PB08
I2C2_SDA: microcontroller.Pin  # PF00
I2C2_SCL: microcontroller.Pin  # PF01
I2C4_SCL: microcontroller.Pin  # PF14
I2C4_SDA: microcontroller.Pin  # PF15
ETH_MDC: microcontroller.Pin  # PC01
ETH_MDIO: microcontroller.Pin  # PA02
ETH_RMII_REF_CLK: microcontroller.Pin  # PA01
ETH_RMII_CRS_DV: microcontroller.Pin  # PA07
ETH_RMII_RXD0: microcontroller.Pin  # PC04
ETH_RMII_RXD1: microcontroller.Pin  # PC05
ETH_RMII_TX_EN: microcontroller.Pin  # PG11
ETH_RMII_TXD0: microcontroller.Pin  # PG13
ETH_RMII_TXD1: microcontroller.Pin  # PB13
SWDIO: microcontroller.Pin  # PA13
SWDCLK: microcontroller.Pin  # PA14


# Members:

# Unmapped:
#   none
