import os,sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
import threading
from cy_app import *

if __name__ == "__main__":

    stop_and_remove_all_containers()

    event = threading.Event()

    fastapi_process = threading.Thread(target=start_service, args=(event,))
    gradio_process = threading.Thread(target=start_gradio, args=(event,))
    api_process = threading.Thread(target=start_api, args=(event,))

    fastapi_process.start()
    gradio_process.start()
    api_process.start()

    fastapi_process.join()
    gradio_process.join()
    api_process.join()