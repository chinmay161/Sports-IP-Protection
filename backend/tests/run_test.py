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
