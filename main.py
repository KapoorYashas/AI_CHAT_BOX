import network
import urequests
import socket
import time
import struct
from machine import ADC, Pin, PWM

# ———————— Wi-Fi Config ————————
SSID       = "ADDRESS"
PASSWORD   = "PASSWORD"
SERVER_URL = "<YOUR_LOCAL_OR_SERVER_URL>/uploads"  # Flask endpoint and /uploads is the folder

# ———————— Hardware Setup ————————
mic    = ADC(Pin(26))                     # Microphone on ADC pin 26
button = Pin(15, Pin.IN, Pin.PULL_UP)     # Button with internal pull-up
led    = Pin(25, Pin.OUT)                 # On-board LED (GP25 on Pico W)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(SSID, PASSWORD)

        # Blink while connecting
        for _ in range(20):  # 10 seconds
            if wlan.isconnected():
                break
            led.toggle()
            time.sleep(0.5)

    if wlan.isconnected():
        print("✅ Connected to Wi-Fi")
        print("IP Address:", wlan.ifconfig()[0])
        led.value(1)  # Solid ON
        return wlan
    else:
        print("❌ Failed to connect")
        led.value(0)  # OFF
        return None

# ------------------ MIC Code (As-is) -------------------




# Audio Configuration
SAMPLE_RATE = 8000
BITS_PER_SAMPLE = 16
CHANNELS = 1

def create_wav_header(sample_rate, num_samples):
    # Generate proper WAV header
    byte_rate   = sample_rate * CHANNELS * (BITS_PER_SAMPLE // 8)
    block_align = CHANNELS * (BITS_PER_SAMPLE // 8)
    data_size   = num_samples * block_align

    header = bytearray()
    header.extend(b'RIFF')
    header.extend((36 + data_size).to_bytes(4, 'little'))
    header.extend(b'WAVE')
    header.extend(b'fmt ')
    header.extend((16).to_bytes(4, 'little'))      # fmt chunk size
    header.extend((1).to_bytes(2, 'little'))       # audio format (PCM)
    header.extend((CHANNELS).to_bytes(2, 'little'))
    header.extend((sample_rate).to_bytes(4, 'little'))
    header.extend((byte_rate).to_bytes(4, 'little'))
    header.extend((block_align).to_bytes(2, 'little'))
    header.extend((BITS_PER_SAMPLE).to_bytes(2, 'little'))
    header.extend(b'data')
    header.extend((data_size).to_bytes(4, 'little'))
    
    return bytes(header)

def record_and_save(filename, duration=5):
    # Record directly to file to save memory
    dc_offset = sum(mic.read_u16() for _ in range(100)) // 100

    with open(filename, 'wb') as f:
        # Write placeholder header
        f.write(create_wav_header(SAMPLE_RATE, 0))

        start = time.ticks_ms()
        sample_count = 0

        # Capture samples
        while time.ticks_diff(time.ticks_ms(), start) < duration * 1000:
            sample = mic.read_u16() - dc_offset
            f.write(struct.pack('<h', sample))
            sample_count += 1
            time.sleep(0.000125)

        # Go back and update header with actual length
        f.seek(0)
        f.write(create_wav_header(SAMPLE_RATE, sample_count))


# ------------------ Send to Flask Server -------------------

def send_audio_to_server(filename):
    try:
        with open(filename, 'rb') as f:
            headers = {'Content-Type': 'audio/wav'}  # Fixed content type
            print('Sending to server...')
            
            response = urequests.post(SERVER_URL, data=f, headers=headers)  # Fixed urequests
            
            if response.status_code == 200:  # Fixed status code from 208 to 200
                with open('response.wav', 'wb') as out:  # Fixed filename extension
                    out.write(response.content)  # Fixed print.write to out.write
                print('Response saved.')
                return True
            else:
                print('Server error:', response.status_code)
                return False
    except Exception as e:  # Fixed variable name from f to e
        print('Error sending file:', e)
        return False

# ------------------ Playback Response -------------------

def play_wav(filename):
    try:
        with open(filename, 'rb') as f:
            header = f.read(44)  # Skip WAV header
            speaker = PWM(Pin(16))
            speaker.freq(8080)
            
            while True:
                frame = f.read(2)
                if not frame:
                    break
                sample = struct.unpack('<h', frame)[0]
                # Convert sample to appropriate PWM duty cycle
                duty = int((sample + 32768) / 65535 * 100)  # Convert 16-bit signed to percentage
                speaker.duty_u16(duty)
    except Exception as e:
        print("Playback error:", e)

# ------------------ Main Loop -------------------

connect_wifi()
print("System ready. Press button to record.")

while True:
    if not button.value():
        led.on()
        print("Recording...")
        filename = "rec.wav"
        record_and_save(filename, duration=5)
        led.off()
        print("Recording complete.")
        s = send_audio_to_server(filename)
        
        if s :
            play_wav("response.wav")
        
        while not button.value():
            time.sleep(0.01)
    time.sleep(0.01)
