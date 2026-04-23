# --- CONFIG ---
$VIDEO_PATH = "C:\Users\Chinmay\Desktop\Vs Code\sports-ip-protection\backend\media_store\20712320-uhd_2160_3840_59fps.mp4"

cd ..

$PYTHON = ".\.venv\Scripts\python.exe"

# --- INSTALL ---
Write-Host "Installing dependencies..."
& $PYTHON -m pip install -r requirements.txt

# --- CHECK FFMPEG ---
Write-Host "Checking ffmpeg..."
ffmpeg -version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "ffmpeg not found. Install and add to PATH."
    exit
}

# --- KEY ---
Write-Host "Generating key..."
$KEY = & $PYTHON -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
$env:WATERMARK_SECRET_KEY = $KEY

# --- FRAME EXTRACTION ---
Write-Host "Extracting frame..."
ffmpeg -y -i $VIDEO_PATH -vf "select=eq(pict_type\,I)" -frames:v 1 real_frame.png

if (!(Test-Path "real_frame.png")) {
    Write-Error "Frame extraction failed."
    exit
}

# --- CREATE PYTHON SCRIPT ---
$PY_SCRIPT = @"
import base64, os
import numpy as np
from PIL import Image
from app.services.watermark import WatermarkService, calculate_psnr

key = base64.b64decode(os.environ["WATERMARK_SECRET_KEY"])
payload = 0xDEADBEEF

frame = np.asarray(Image.open("real_frame.png").convert("RGB"), dtype=np.uint8)

wm = WatermarkService.embed(frame, payload, key, alpha=8)
Image.fromarray(wm).save("real_frame_watermarked.png")

recovered, confidence = WatermarkService.extract(wm, key)

print("Recovered:", hex(recovered))
print("Confidence:", confidence)
print("PSNR:", calculate_psnr(frame, wm))
"@

$PY_FILE = "run_test.py"
$PY_SCRIPT | Out-File -Encoding utf8 $PY_FILE

# --- RUN PYTHON ---
Write-Host "Running test..."
$env:PYTHONPATH='.'
& $PYTHON $PY_FILE

Write-Host "Done. Check real_frame_watermarked.png"