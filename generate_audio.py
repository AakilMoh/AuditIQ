import os
import io
import re
import textwrap
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment

load_dotenv()

# Initialize using your exact config style for Groq routing
tts_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

INPUT_DIR = "synthetic_transcripts"
OUTPUT_DIR = "synthetic_audio"
TTS_MODEL = "canopylabs/orpheus-v1-english"

# Voice routing matching Orpheus persona strengths
VOICES = {
    "Agent": "troy",           # Confident male persona for the agency side
    "Debtor": "autumn",        # Highly expressive female persona for consumers
    "Receptionist": "hannah",  # Clear professional tone for third parties
    "Third-Party": "austin",   # Alternative distinct male voice
    "Lawyer": "daniel"         # Authoritative tone for legal scenarios
}

def split_text_preserving_directions(text, max_chars=180):
    """
    Safely wraps text into chunks below the 200-character limit 
    while keeping bracketed vocal instructions intact where possible.
    """
    # If the whole turn is short, return it immediately
    if len(text) <= max_chars:
        return [text]
        
    # Split text into sentences or clean segments
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    
    # Extract any global vocal direction at the start of the line (e.g., [angry])
    global_direction = ""
    direction_match = re.match(r'^(\[[^\]]+\])\s*', text)
    if direction_match:
        global_direction = direction_match.group(1) + " "

    for sentence in sentences:
        # Check if adding the next sentence exceeds the limit
        test_chunk = current_chunk + (" " if current_chunk else "") + sentence
        if len(test_chunk) <= max_chars:
            current_chunk = test_chunk
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # If a single sentence is still too long, wrap it mechanically
            if len(sentence) > max_chars:
                wrapped_parts = textwrap.wrap(sentence, width=max_chars - len(global_direction), break_long_words=False)
                for part in wrapped_parts:
                    chunks.append(global_direction + part if global_direction and not part.startswith('[') else part)
                current_chunk = ""
            else:
                current_chunk = global_direction + sentence if global_direction and not sentence.startswith('[') else sentence
                
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

def generate_pipeline_audio():
    # Ensure folders exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if not os.path.exists(INPUT_DIR):
        print(f"❌ Error: The directory '{INPUT_DIR}' was not found in the running context.")
        return

    print("🎙️ Starting Groq/Orpheus Multi-Voice Audio Generation Pipeline...\n")
    
    # Read files exactly as laid out in image_b2d028.png
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".txt") or os.path.isfile(os.path.join(INPUT_DIR, f))]
    
    if not files:
        print(f"⚠️ No files found inside the '{INPUT_DIR}' directory. Check extensions.")
        return

    for filename in sorted(files):
        filepath = os.path.join(INPUT_DIR, filename)
        print(f"📄 Processing transcript text: {filename}")
        
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        full_call_audio = AudioSegment.empty()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or ":" not in line: 
                continue
                
            speaker, text = line.split(":", 1)
            speaker = speaker.strip()
            text = text.strip()
            
            # Clean out any structural tracking tags if present
            text = re.sub(r'\[source:\s*\d+\]', '', text).strip()
            if not text: 
                continue
            
            # Dynamic voice matching based on role or name keyword variations
            voice_key = "Agent" if "agent" in speaker.lower() else "Debtor"
            if "lawyer" in speaker.lower() or "specter" in filename.lower() and "agent" not in speaker.lower():
                voice_key = "Lawyer"
            elif "third" in speaker.lower() or "shelby" in filename.lower() and "agent" not in speaker.lower():
                voice_key = "Third-Party"
                
            selected_voice = VOICES.get(voice_key, "daniel")
            
            # Chunk the speech to prevent 200-character payload rejections
            chunks = split_text_preserving_directions(text)
            
            for chunk in chunks:
                try:
                    # Request generation using the exact parameters verified in the docs
                    response = tts_client.audio.speech.create(
                        model=TTS_MODEL,
                        voice=selected_voice,
                        input=chunk,
                        response_format="wav"  # API strictly enforces wav output
                    )
                    
                    # Read the binary stream directly in memory via Pydub
                    byte_stream = io.BytesIO(response.content)
                    segment = AudioSegment.from_file(byte_stream, format="wav")
                    
                    # Smooth intra-sentence pacing addition
                    full_call_audio += segment + AudioSegment.silent(duration=100)
                    
                except Exception as e:
                    print(f"  ❌ Generation error on line {line_num} ({speaker}): {e}")
            
            # Add a natural conversational delay when speakers shift turns (450ms)
            full_call_audio += AudioSegment.silent(duration=450)
                
        # Export the composite track to an MP3 file matching your audio consumer pipeline
        output_filename = os.path.splitext(filename)[0] + ".mp3"
        output_filepath = os.path.join(OUTPUT_DIR, output_filename)
        
        if len(full_call_audio) > 0:
            full_call_audio.export(output_filepath, format="mp3")
            print(f"✨ Successfully compiled entire call audio -> {output_filepath}\n")
        else:
            print(f"⚠️ Skipped saving {filename} due to empty audio stream structure.\n")

if __name__ == "__main__":
    generate_pipeline_audio()