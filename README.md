# About
Simple python module to communicate with an LPC2xxx ISP debugger

# Usage
Connect a USB-UART device as follows:
- UART Rx to LPC2xxx UART0 Tx
- UART Tx to LPC2xxx UART0 Rx
- UART DTR to LPC2xxx RESET
- UART RTS to LPC2xxx ISP Enable

Then use programmatically or interactively (such as through ipython) to interact 
with the ISP debugger:

```python
import lpcisp
debug = lpcisp.ISP('/dev/ttyUSB0', 115200, 12000)
firmware = debug.read_memory(0, 0x40000)
```
