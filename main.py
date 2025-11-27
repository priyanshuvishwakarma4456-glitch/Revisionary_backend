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

api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

def clean_text(raw_text):
    cleaned = re.sub(r'[^\x20-\x7E\n]', '', raw_text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

@app.route('/')
def home():
    return "Python Quiz Server (Index Mode)"

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
        try:
            reader = PdfReader(file)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted: context_text += extracted + "\n"
            context_text = clean_text(context_text)
            if len(context_text) < 50: return jsonify({"error": "PDF unreadable/scanned."}), 400
        except: return jsonify({"error": "PDF Error"}), 500
    elif topic:
        context_text = f"Generate questions about: {topic}"
    else:
        return jsonify({"error": "No input"}), 400

    # --- ASK GROQ (Requesting Indexes) ---
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
        {context_text[:15000]}
        
        OUTPUT JSON FORMAT:
        [
            {{
                "question": "Question text?", 
                "type": "single",  // OR "multiple"
                "options": ["Option A", "Option B", "Option C", "Option D"], 
                "correct_indices": [0], // List of correct indexes. Example for A & C: [0, 2]
                "answer_text": "The text explanation of the answer",
                "explanation": "Why it is correct."
            }}
        ]
        """

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.2, 
        )
        
        content = chat.choices[0].message.content
        json_str = content.replace("```json", "").replace("```", "").strip()
        
        if not json_str.startswith("["): raise ValueError("Invalid JSON")
        
        return jsonify(json.loads(json_str))

    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": "AI Error. Try again."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)


