import os
import re
import json
import random
import traceback
import unicodedata
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS
import PyPDF2
from groq import Groq

app = Flask(__name__)
CORS(app)

# --- GROQ SETUP ---
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

def clean_text(raw_text):
    if not raw_text: return ""
    text = unicodedata.normalize('NFKC', raw_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- ROBUST JSON EXTRACTOR ---
def extract_json(text):
    # 1. Try to find the JSON list using Regex (Most reliable)
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        return match.group(0)
    
    # 2. Fallback: Find brackets manually
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1:
        return text[start:end+1]
    
    # 3. Last resort: Try to close an open bracket
    if start != -1:
        return text[start:] + "]"
        
    return "[]"

# --- JSON REPAIR ---
def safe_json_load(json_str):
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Common AI error: Trailing commas. Fix: ,] -> ] and ,} -> }
        try:
            fixed_str = re.sub(r',\s*\]', ']', json_str)
            fixed_str = re.sub(r',\s*\}', '}', fixed_str)
            return json.loads(fixed_str)
        except:
            return []

# --- LOGIC ASSEMBLER ---
def assemble_quiz(raw_data, target_count):
    final_quiz = []
    
    if not isinstance(raw_data, list):
        return []

    for item in raw_data:
        # Clean text
        question = str(item.get('question', '')).replace('$', '').replace('\\', '')
        correct_txt = str(item.get('correct_answer', '')).replace('$', '').replace('\\', '')
        wrong_list = item.get('wrong_answers', [])
        explanation = str(item.get('explanation', ''))

        # Clean wrongs
        clean_wrongs = []
        for w in wrong_list:
            w = str(w).replace('$', '').replace('\\', '')
            clean_wrongs.append(w)

        # Pad or Cut to get exactly 3 wrong answers
        while len(clean_wrongs) < 3:
            clean_wrongs.append("None of the above")
        clean_wrongs = clean_wrongs[:3]

        # Combine and Shuffle
        all_options = [correct_txt] + clean_wrongs
        random.shuffle(all_options)

        # Find Index
        try:
            correct_index = all_options.index(correct_txt)
        except:
            correct_index = 0 

        # Build Object
        quiz_item = {
            "question": question,
            "options": all_options,
            "correct_indices": [correct_index],
            "explanation": explanation,
            "type": "single"
        }
        final_quiz.append(quiz_item)

    return final_quiz[:target_count]

@app.route('/')
def home():
    return "Revisionary Server: Robust JSON Mode"

@app.route('/generate-quiz', methods=['POST'])
@app.route('/generate_quiz', methods=['POST'])
def generate_quiz():
    if not client: return jsonify({"error": "Missing API Key"}), 500

    try:
        num_questions = int(request.form.get('count', '5'))
        if num_questions > 20: num_questions = 20
    except:
        num_questions = 5

    context_text = ""
    
    # --- FILE HANDLING ---
    if 'pdf' in request.files:
        file = request.files['pdf']
        filename = file.filename.lower()
        
        # Block Images for now (to prevent 400 error)
        if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
             return jsonify({"error": "Image AI updating. Please use PDF."}), 400
             
        try:
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                return jsonify({"error": "Uploaded file is empty."}), 400
            file.seek(0)

            reader = PyPDF2.PdfReader(file)
            limit = min(len(reader.pages), 15)
            for i in range(limit):
                page_text = reader.pages[i].extract_text()
                if page_text: context_text += page_text + "\n"
            
            context_text = clean_text(context_text)
            if len(context_text) < 50: return jsonify({"error": "PDF has no readable text."}), 400
            context_text = context_text[:15000]
        except Exception as e:
            print(f"PDF Error: {e}")
            return jsonify({"error": "PDF Processing Failed."}), 500

    elif request.form.get('topic'):
        context_text = request.form.get('topic')

    # --- AI GENERATION ---
    try:
        print(f"Asking Groq for {num_questions} questions...")

        # Explicit Prompt for Separate Correct/Wrong answers
        system_instructions = f"""
        You are an expert quiz generator.
        
        TASK: Generate exactly {num_questions} questions based on the text.
        
        CRITICAL RULES:
        1. **Structure**: Return a JSON LIST of objects.
        2. **Format**: Each object MUST have: 'question', 'correct_answer' (string), 'wrong_answers' (list of 3 strings), 'explanation'.
        3. **Math**: If text says "2 is irrational", implies "Root 2". Fix it.
        4. **No Markdown**: Do not write ```json.
        
        Example JSON:
        [
          {{
            "question": "What is 2+2?",
            "correct_answer": "4",
            "wrong_answers": ["3", "5", "6"],
            "explanation": "2 plus 2 equals 4."
          }}
        ]
        """

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": f"Context:\n{context_text}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.2, 
            max_tokens=5000
        )

        json_str = extract_json(chat.choices[0].message.content)
        
        # Use safe loader to prevent crash
        data = safe_json_load(json_str)
        
        if not data: 
            print("AI Output was bad:", chat.choices[0].message.content[:200])
            return jsonify({"error": "AI response was invalid."}), 500

        # Assembly Line (Python Logic)
        final_data = assemble_quiz(data, num_questions)
        
        if not final_data: return jsonify({"error": "Failed to assemble quiz."}), 500

        return jsonify(final_data)

    except Exception as e:
        print(f"Server Error: {e}")
        traceback.print_exc()
        return jsonify({"error": "Server Error."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
    





