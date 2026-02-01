import network
import urequests
import socket
import time
import struct
from machine import ADC, Pin, PWM

# ———————— Wi-Fi Config ————————
SSID       = "ADDRESS"
PASSWORD   = "PASSWORD"
SERVER_URL = "<YOUR_LOCAL_OR_SERVER_URL>/uploads"  # Flask endpoint

# ———————— Hardware Setup ————————
mic    = ADC(Pin(26))                     # Microphone on ADC pin 26
button = Pin(15, Pin.IN, Pin.PULL_UP)     # Button with internal pull-up
led    = Pin(25, Pin.OUT)                 # On-board LED (GP25)


# =====================================================
#            AUDIO & SYSTEM PARAMETERS

# =====================================================
SAMPLE_RATE = 8000
BITS_PER_SAMPLE = 16
CHANNELS = 1
RECORD_DURATION = 5
BUFFER_DELAY = 0.000125
DC_OFFSET_SAMPLES = 100

# ---------- Edge Analytics Parameters (2023–2024 tech) ----------
# On-device audio analysis before cloud transmission
ENERGY_WINDOW = 50              # Samples used for energy analysis
ENERGY_THRESHOLD = 500          # Initial adaptive threshold
ADAPT_RATE = 0.1                # Learning rate for threshold update
EDGE_ANALYTICS_ENABLED = True   # Enables edge-level prediction


# =====================================================
#               WI-FI CONNECTION
# =====================================================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(SSID, PASSWORD)

        for _ in range(20):
            if wlan.isconnected():
                break
            led.toggle()
            time.sleep(0.5)

    if wlan.isconnected():
        print("✅ Connected to Wi-Fi")
        print("IP Address:", wlan.ifconfig()[0])
        led.value(1)
        return True
    else:
        print("❌ Failed to connect")
        led.value(0)
        return False


# =====================================================
#               WAV HEADER CREATION
# =====================================================
def create_wav_header(sample_rate, num_samples):
    byte_rate   = sample_rate * CHANNELS * (BITS_PER_SAMPLE // 8)
    block_align = CHANNELS * (BITS_PER_SAMPLE // 8)
    data_size   = num_samples * block_align

    header = bytearray()
    header.extend(b'RIFF')
    header.extend((36 + data_size).to_bytes(4, 'little'))
    header.extend(b'WAVE')
    header.extend(b'fmt ')
    header.extend((16).to_bytes(4, 'little'))
    header.extend((1).to_bytes(2, 'little'))
    header.extend((CHANNELS).to_bytes(2, 'little'))
    header.extend((sample_rate).to_bytes(4, 'little'))
    header.extend((byte_rate).to_bytes(4, 'little'))
    header.extend((block_align).to_bytes(2, 'little'))
    header.extend((BITS_PER_SAMPLE).to_bytes(2, 'little'))
    header.extend(b'data')
    header.extend((data_size).to_bytes(4, 'little'))

    return bytes(header)


# =====================================================
#           RECORD + EDGE AUDIO ANALYTICS
# =====================================================
def record_and_save(filename, duration=RECORD_DURATION):
    global ENERGY_THRESHOLD

    # --- DC Offset Calibration ---
    dc_offset = sum(mic.read_u16() for _ in range(DC_OFFSET_SAMPLES)) // DC_OFFSET_SAMPLES

    with open(filename, 'wb') as f:
        f.write(create_wav_header(SAMPLE_RATE, 0))

        start = time.ticks_ms()
        sample_count = 0

        # ---------- REAL-TIME AUDIO CAPTURE ----------
        while time.ticks_diff(time.ticks_ms(), start) < duration * 1000:
            sample = mic.read_u16() - dc_offset
            f.write(struct.pack('<h', sample))
            sample_count += 1
            time.sleep(BUFFER_DELAY)

        # Update WAV header with actual size
        f.seek(0)
        f.write(create_wav_header(SAMPLE_RATE, sample_count))

        # =================================================
        # 🔍 EDGE AUDIO ANALYTICS (2023–2024)
        # -------------------------------------------------
        # • Extracts signal energy on-device
        # • Predicts speech vs silence
        # • Adapts threshold over time (lightweight learning)
        # • Reduces unnecessary cloud uploads
        # =================================================
        if EDGE_ANALYTICS_ENABLED:
            energy_sum = 0
            f.seek(44)  # Skip WAV header

            for _ in range(ENERGY_WINDOW):
                frame = f.read(2)
                if not frame:
                    break
                sample = struct.unpack('<h', frame)[0]
                energy_sum += abs(sample)

            avg_energy = energy_sum / ENERGY_WINDOW

            # Adaptive threshold update
            ENERGY_THRESHOLD = (ENERGY_THRESHOLD * (1 - ADAPT_RATE)) + (avg_energy * ADAPT_RATE)

            # Predictive decision
            if avg_energy < ENERGY_THRESHOLD:
                print("Edge Analytics: Silence predicted — upload skipped")
                return False

    return True


# =====================================================
#               SEND TO FLASK SERVER
# =====================================================
def send_audio_to_server(filename):
    try:
        with open(filename, 'rb') as f:
            headers = {'Content-Type': 'audio/wav'}
            print("Sending to server...")
            response = urequests.post(SERVER_URL, data=f, headers=headers)

            if response.status_code == 200:
                with open('response.wav', 'wb') as out:
                    out.write(response.content)
                print("Response saved.")
                return True
            else:
                print("Server error:", response.status_code)
                return False
    except Exception as e:
        print("Error sending file:", e)
        return False


# =====================================================
#               PLAY RESPONSE AUDIO
# =====================================================
def play_wav(filename):
    try:
        with open(filename, 'rb') as f:
            f.read(44)
            speaker = PWM(Pin(16))
            speaker.freq(8080)

            while True:
                frame = f.read(2)
                if not frame:
                    break
                sample = struct.unpack('<h', frame)[0]
                duty = int((sample + 32768) / 65535 * 100)
                speaker.duty_u16(duty)
    except Exception as e:
        print("Playback error:", e)


# =====================================================
#                    MAIN LOOP
# =====================================================
connect_wifi()
print("System ready. Press button to record.")

while True:
    if not button.value():
        led.on()
        print("Recording...")

        speech_detected = record_and_save("rec.wav")

        led.off()
        print("Recording complete.")

        if speech_detected:
            s = send_audio_to_server("rec.wav")
            if s:
                play_wav("response.wav")

        while not button.value():
            time.sleep(0.01)

    time.sleep(0.01)
