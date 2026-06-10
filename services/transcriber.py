import os
import logging
from datetime import datetime
from core.config import audio_client

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("transcriber")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(f"logs/transcriber_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [Transcriber] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[Transcriber] %(message)s'))

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
# ---------------------------------------------------------

def transcribe_call(audio_file_path: str, debug=False) -> str:
    """
    Takes a path to an audio file (.mp3, .wav) and converts it to text
    using GROQ hosted Whisper Large v3 model.
    """
    if not os.path.exists(audio_file_path):
        error_msg = f"Error: Audio file not found at {audio_file_path}"
        logger.error(error_msg)
        return error_msg
    
    if debug:
        logger.info(f"Uploading '{audio_file_path}' to Groq Cloud")

    try:
        # opening the audio file in binary read mode ('rb')
        with open(audio_file_path, "rb") as audio_file:
            # using the Audio Client
            response = audio_client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3",
                response_format="json" # returning a JSON object containing a 'text' key 
            )
        
        transcript = response.text

        if debug:
            logger.info(f"Success! Transcript generated.\n{'-' * 50}\n{transcript}\n{'-' * 50}")

        return transcript

    except Exception as e:
        error_msg = f"Error during transcription: {str(e)}"
        logger.error(error_msg)
        return error_msg

# Execution Block
if __name__ == "__main__":
    logger.info("Testing Transcriber Module....")

    test_audio = "test_call.mp3"

    if os.path.exists(test_audio):
        result = transcribe_call(test_audio, debug=True)
    else:
        logger.error(f"Drop an audio file named '{test_audio}' to test")