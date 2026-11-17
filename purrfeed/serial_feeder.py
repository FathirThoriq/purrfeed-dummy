import logging
import threading
import serial

logger = logging.getLogger(__name__)


def trigger_feed(port="COM12", baudrate=115200):
    """Kirim perintah 'F\n' ke ESP32 melalui port serial COM12 untuk menggerakkan servo."""
    if not port:
        return False
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baudrate
        ser.timeout = 1
        ser.dtr = False
        ser.rts = False
        ser.open()
        ser.write(b"F\n")
        ser.flush()
        ser.close()
        logger.info(f"[SERIAL] Berhasil mengirim sinyal buka servo ke {port}")
        print(f"[SERIAL] Berhasil mengirim sinyal buka servo ke {port}")
        return True
    except Exception as e:
        logger.warning(f"[SERIAL] Gagal mengirim sinyal ke {port}: {e}")
        print(f"[SERIAL] Gagal mengirim sinyal ke {port}: {e}")
        return False


def trigger_feed_async(port="COM12", baudrate=115200):
    """Jalankan trigger_feed di background thread agar tidak menunda HTTP response."""
    thread = threading.Thread(target=trigger_feed, args=(port, baudrate), daemon=True)
    thread.start()
    return thread
