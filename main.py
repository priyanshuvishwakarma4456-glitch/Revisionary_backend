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

# --- CLEANER ---
def clean_text(raw_text):
    cleaned = re.sub(r'[^\x20-\x7E\n]', '', raw_text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

# --- JSON REPAIR (The Magic Fix) ---
def repair_json(json_str):
    # 1. Strip markdown
    json_str = json_str.replace("```json", "").replace("```", "").strip()
    
    # 2. Find the start of the list
    start = json_str.find('[')
    if start == -1: return "[]" # No list found
    
    # 3. Check if it ends correctly
    end = json_str.rfind(']')
    if end == -1 or end < start:
        # It got cut off! Let's fix it.
        # Find the last closing curly brace '}'
        last_brace = json_str.rfind('}')
        if last_brace != -1:
            # Cut off everything after the last valid object and add a closing bracket
            json_str = json_str[:last_brace+1] + "]"
        else:
            return "[]" # It didn't even finish one question
    else:
        # It ended correctly, just trim anything after
        json_str = json_str[start:end+1]
        
    return json_str

@app.route('/')
def home():
    return "Python Quiz Server (Repair Mode)"

@app.route('/generate-quiz', methods=['POST'])
def generate_quiz():
    print("--- Request Received ---")
    
    if not client: return jsonify({"error": "Missing API Key"}), 500

    topic = request.form.get('topic', '').strip()
    try:
        num_questions = int(request.form.get('count', '5'))
        if num_questions > 50: num_questions = 50
    except (ValueError, TypeError):
        num_questions = 5

    context_text = ""
    
    if 'pdf' in request.files:
        file = request.files['pdf']
        if file.filename == '': return jsonify({"error": "No file"}), 400
        try:
            reader = PdfReader(file)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted: context_text += extracted + "\n"
            context_text = clean_text(context_text)
            if len(context_text) < 50: return jsonify({"error": "PDF Unreadable/Scanned"}), 400
            context_text = context_text[:12000]
        except Exception as e:
            print(f"PDF processing error: {e}")
            return jsonify({"error": "PDF Error"}), 500
    
    elif topic:
        context_text = f"Generate questions about: {topic}"
    else:
        return jsonify({"error": "No Input"}), 400

    # --- ASK GROQ ---
    try:
        print(f"Asking Groq for {num_questions} questions...")
        
        prompt = f"""
        You are a quiz generator.
        
        TASK:
        Create exactly {num_questions} multiple choice questions.
        - STRICTLY limit the output to {num_questions} questions. Do not generate more than this.
        - Determine if a question is 'single' choice or 'multiple' choice.
        - Instead of answer text, provide the INDEX of the correct option(s).
        - Index 0 = A, Index 1 = B, Index 2 = C, Index 3 = D.
        
        SOURCE:
        {context_text}
        
        OUTPUT JSON FORMAT:
        [
            {{
                "question": "Question text?", 
                "type": "single",  // OR "multiple"
                "options": ["Option A", "Option B", "Option C", "Option D"], 
                "correct_indices": [0], // List of correct indexes. Example for A & C: [0, 2]
                "explanation": "Why it is correct."
            }}
        ]
        """
        

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=8000, # Try to get as much text as possible
        )
        
        raw_content = chat.choices[0].message.content
        
        # REPAIR THE JSON if it's broken
        json_str = repair_json(raw_content)
        
        try:
            data = json.loads(json_str)
            print(f"Success! Generated {len(data)} questions.")
            return jsonify(data)
        except json.JSONDecodeError:
            print("Repair Failed. Raw:", raw_content)
            return jsonify([
                {"question": "Error: The AI got cut off.", "options": ["Try fewer questions", "Try again"], "correct_indices": [0], "type": "single", "explanation": "45 questions is a lot for the free tier."}
            ])

    except Exception as e:
        print(f"AI Error: {e}")
        if "429" in str(e): return jsonify({"error": "Daily Limit Reached."}), 500
        return jsonify({"error": "AI Generation Failed."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)




