import requests
import json
import sys
import os

# The endpoint we just built
url = "http://localhost:8000/api/v1/audit/stream"

# We will use your existing test file
audio_path = "eval_audio/case_5_david_rose.mp3" 

print("Initiating Stream Test\n")

with open(audio_path, "rb") as audio_file:
    # 1. Prepare the payload exactly as the frontend will send it
    safe_filename = os.path.basename(audio_path)
    files = {"audio_file": (audio_path, audio_file, "audio/mpeg")}
    data = {
        "debtor_id": 8,          
        "think_mode": "True"     # Turning on the heavy Llama 70B
    }

    # 2. Hit the API and stream the response
    try:
        response = requests.post(url, files=files, data=data, stream=True)
        response.raise_for_status()

        # 3. Catch the Server-Sent Events (SSE) in real-time
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data: "):
                    # Extract the JSON payload
                    payload_str = decoded_line[6:]
                    
                    # Skip empty payloads or keep-alives
                    if not payload_str.strip():
                        continue 
                    try:
                        event_data = json.loads(payload_str)
                    except json.JSONDecodeError as e:
                        # If the token stream mangles a character, log it
                        print(f"\n[Warning: Skipped unparseable token payload: {payload_str}]")
                        continue

                    # Print the live stream steps to the terminal
                    step = event_data.get("step")
                    if step == "init":
                        print(f"📦 [INIT] {event_data['message']}")
                    elif step == "database":
                        print(f"🗄️  [DB] {event_data['message']}")
                    elif step == "transcribing":
                        print(f"🎙️  [WHISPER] {event_data['message']}")
                    elif step == "transcript_ready":
                        print(f"\n📝 [TRANSCRIPT]:\n{event_data['transcript']}\n")
                    elif step == "auditing":
                        print(f"🧠 [AI AUDITOR] {event_data['message']}")
                        print("-" * 50)

                    elif step == "stream":
                        sys.stdout.write(event_data.get('chunk', ''))
                        sys.stdout.flush()
                        
                    elif step == "verifying":
                        print(f"\n\n[VERIFIER] {event_data['message']}")
                    
                    elif step == "complete":
                        print("\n" + "="*70)
                        print("✅ [FINAL RESULT SUMMARY]")
                        print("="*70)
                        result = event_data['result']
                        for key, value in result.items():
                            print(f"\n🔹 {key.upper()}:")
                            if isinstance(value, str):
                                formatted_value = value.replace('\n', '\n  ')
                                print(f"  {formatted_value}")
                            elif isinstance(value, list):
                                if not value:
                                    print("  [None]")
                                for item in value:
                                    print(f"  - {item}")
                            else:
                                print(f"  {value}")
                        print("\n" + "="*70 + "\n")

                        #automatically saving the final result for evaluations
                        log_dir = "eval_logs"
                        os.makedirs(log_dir, exist_ok=True)

                        # Create a safe filename using the audio filename 
                        # e.g., "case_1_john_doe_result.json"
                        safe_name = os.path.splitext(os.path.basename(audio_path))[0]
                        log_path = os.path.join(log_dir, f"{safe_name}_result.json")
                        
                        with open(log_path, "w", encoding="utf-8") as f:
                            json.dump(result, f, indent=4)
                            
                        print(f"💾 [SAVED] Log successfully written to: {log_path}\n")
                        
                    elif step == "error":
                        print(f"\n[ERROR]: {event_data['message']}")

    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to server: {e}")

print("\nStream Test Complete.")