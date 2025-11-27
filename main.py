import os
import re
import json
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from pypdf import PdfReader
from groq import Groq

app = Flask(__name__)
CORS(app)

# API Key Check
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

def clean_text(raw_text):
    cleaned = re.sub(r'[^\x20-\x7E\n]', '', raw_text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

# --- SMART JSON EXTRACTOR ---
# --- SMART JSON REPAIR ---
def extract_json(text):
    # 1. Remove markdown code blocks if present
    text = text.replace("```json", "").replace("```", "").strip()

    # 2. Find the start of the list
    start = text.find('[')
    if start == -1: return "[]" # No list found

    # 3. Check if it ends correctly
    end = text.rfind(']')

    if end != -1 and end > start:
        # It looks complete, return it
        return text[start:end+1]
    else:
        # 4. IT IS CUT OFF! Let's repair it.
        # Find the last closing curly brace '}' which marks the end of the last *complete* question
        last_brace = text.rfind('}')

        if last_brace != -1 and last_brace > start:
            # Cut off the broken part after the last '}' and add a closing ']'
            print("⚠️ JSON was cut off. Repairing to save valid questions...")
            return text[start:last_brace+1] + "]"

    return "[]" # Failed to recover


@app.route('/')
def home():
    return "Priyanshu is running (full power Mode)"

@app.route('/generate-quiz', methods=['POST'])
def generate_quiz():
    if not client: return jsonify({"error": "Missing API Key"}), 500

    topic = request.form.get('topic', '').strip()
    try:
        num_questions = int(request.form.get('count', '5'))
        if num_questions > 50: num_questions = 50
    except:
        num_questions = 5

    context_text = ""
    
    # --- PDF HANDLING ---
    if 'pdf' in request.files:
        file = request.files['pdf']
        if file.filename == '': return jsonify({"error": "No file"}), 400
        try:
            reader = PdfReader(file)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted: context_text += extracted + "\n"
            context_text = clean_text(context_text)
            if len(context_text) < 50: return jsonify({"error": "PDF unreadable/scanned."}), 400
            context_text = context_text[:12000]
        except: return jsonify({"error": "PDF Error"}), 500
    elif topic:
        context_text = f"Generate questions about: {topic}"
    else:
        return jsonify({"error": "No input"}), 400

    # --- ASK GROQ (With Partial Recovery) ---
    try:
        print(f"Asking Groq for {num_questions} questions...")

        prompt = f"""
        You are a quiz generator.

        TASK:
        Create {num_questions} multiple choice questions.
        - Determine if a question is 'single' choice or 'multiple' choice.
        - Instead of answer text, provide the INDEX of the correct option(s).
        - Index 0 = A, Index 1 = B, Index 2 = C, Index 3 = D.

        SOURCE:
        {context_text}

        OUTPUT JSON FORMAT:
        [
            {{
                "question": "Question text?", 
                "type": "single",
                "options": ["Option A", "Option B", "Option C", "Option D"], 
                "correct_indices": [0],
                "explanation": "Why it is correct."
            }}
        ]
        """

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.2, 
            max_tokens=8000, # Allow max length
        )

        # Use the new repair function
        json_str = extract_json(chat.choices[0].message.content)

        try:
            data = json.loads(json_str)
            
            # STRICT LIMITER: If AI made too many, chop off the extras
            if len(data) > num_questions:
                print(f"AI made too many ({len(data)}). Trimming to {num_questions}.")
                data = data[:num_questions]
                
            print(f"Success! Sending {len(data)} questions.")
            return jsonify(data)
                    
        except json.JSONDecodeError:
            print("Repair failed. Raw output:", chat.choices[0].message.content)
            return jsonify({"error": "AI output damaged. Try fewer questions."}), 500

    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": "AI Error. Try again."}), 500

        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)





