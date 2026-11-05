import os

from purrfeed import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "10.125.173.183"), port=int(os.environ.get("PORT", 5000)), threaded=True)
