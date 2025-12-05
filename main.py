import os
import re
import json
import traceback
import unicodedata
from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
from groq import Groq

app = Flask(__name__)
CORS(app)

# --- GROQ SETUP ---
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

if not client:
    print("⚠️ WARNING: GROQ_API_KEY not found. App will fail to generate.")

# --- GARBLED TEXT HANDLER ---
def clean_text(raw_text):
    if not raw_text: return ""
    text = unicodedata.normalize('NFKC', raw_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find('[')
    if start == -1: return "[]"
    text = text[start:] 
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    cursor = len(text)
    while cursor > 0:
        cursor = text.rfind('}', 0, cursor)
        if cursor == -1: break 
        candidate = text[:cursor+1] + "]"
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return "[]"

@app.route('/')
def home():
    return "Revisionary is running on Replit (Compat Mode)"

# --- CRITICAL FIX: USING HYPHEN (-) TO MATCH YOUR APK ---
@app.route('/generate-quiz', methods=['POST'])
def generate_quiz():
    if not client: return jsonify({"error": "Missing API Key"}), 500

    topic = request.form.get('topic', '').strip()
    try:
        num_questions = int(request.form.get('count', '5'))
        if num_questions > 20: num_questions = 20
    except:
        num_questions = 5

    context_text = ""
    
    # --- PDF HANDLING (OPTIMIZED) ---
    if 'pdf' in request.files:
        file = request.files['pdf']
        if file.filename == '': return jsonify({"error": "No file"}), 400
        try:
            with pdfplumber.open(file) as pdf:
                # Limit to 15 pages to prevent crash on large books like Gulliver's Travels
                max_pages = 15
                for i, page in enumerate(pdf.pages):
                    if i >= max_pages: break 
                    extracted = page.extract_text()
                    if extracted: context_text += extracted + "\n"
            
            context_text = clean_text(context_text)
            
            if len(context_text) < 50: return jsonify({"error": "PDF unreadable/scanned."}), 400
            context_text = context_text[:18000] 
        except Exception as e: 
            print(f"PDF Error: {e}")
            return jsonify({"error": "PDF Error"}), 500
    elif topic:
        context_text = f"Generate questions about: {topic}"
    else:
        return jsonify({"error": "No input"}), 400

    # --- ASK GROQ ---
    try:
        print(f"Asking Groq for {num_questions} questions...")

        prompt = f"""
        You are a quiz generator.
        
        TASK:
        Generate exactly {num_questions} multiple choice questions in strictly valid JSON format.
        
        RULES:
        1. Output MUST be a raw JSON list [{{...}}, {{...}}].
        2. Do not include any text outside the JSON.
        3. "correct_indices" must be a list of integers (0=A, 1=B, 2=C, 3=D).
        
        CONTENT:
        {context_text}

        JSON STRUCTURE:
        [
            {{
                "question": "Question?", 
                "type": "single",
                "options": ["A", "B", "C", "D"], 
                "correct_indices": [0],
                "explanation": "Exp"
            }}
        ]
        """

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", 
            temperature=0.2, 
            max_tokens=8000, 
        )

        json_str = extract_json(chat.choices[0].message.content)
        data = json.loads(json_str)
        
        if not data: return jsonify({"error": "AI response was too broken to fix."}), 500

        if len(data) > num_questions:
            data = data[:num_questions]

        print(f"Success! Sending {len(data)} questions.")
        return jsonify(data)

    except Exception as e:
        print(f"Backend Error: {e}")
        traceback.print_exc()
        return jsonify({"error": "Server Processing Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
    





