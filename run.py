from app import create_app
from app.config import Config
import os

app = create_app()

# Ensure directories exist
os.makedirs(Config.VIDEOS_DIR, exist_ok=True)
os.makedirs(Config.FRAMES_DIR, exist_ok=True)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
