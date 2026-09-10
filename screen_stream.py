import cv2
from flask import Flask, Response
import mss
import numpy as np

app = Flask(__name__)


def generate_frames():
  # Initialisation de la capture d'écran haute performance
  with mss.mss() as sct:
    # Capture le premier écran principal
    monitor = sct.monitors[1]
    while True:
      # Capture l'écran sous forme de tableau numpy
      img = np.array(sct.grab(monitor))
      # Convertit le format BGRA en BGR (standard OpenCV)
      frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

      # Compresse l'image en JPEG (qualité 60 pour réduire la bande passante réseau)
      ret, buffer = cv2.imencode(
          '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60]
      )
      frame_bytes = buffer.tobytes()

      # Envoie l'image au format flux MJPEG
      yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


@app.route('/')
def index():
  # Page HTML simple qui intègre le flux vidéo
  return """
    <html>
        <head><title>Partage d'ecran Reseau</title></head>
        <body style="background: #111; color: #fff; text-align: center;">
            <h2>Flux en direct du PC distant</h2>
            <img src="/video_feed" style="width: 90%; border: 2px solid #444;" />
        </body>
    </html>
    """


@app.route('/video_feed')
def video_feed():
  return Response(
      generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame'
  )


if __name__ == '__main__':
  # host='0.0.0.0' permet d'écouter sur toutes les interfaces réseau (accessible depuis le LAN)
  app.run(host='0.0.0.0', port=5000)