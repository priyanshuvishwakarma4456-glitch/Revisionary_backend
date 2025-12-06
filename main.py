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

def extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1:
        return text[start:end+1]
    if start != -1: return text[start:] + "]"
    return "[]"

# --- NEW LOGIC ASSEMBLER ---
# This builds the quiz options manually in Python so they can never be wrong.
def assemble_quiz(raw_data, target_count):
    final_quiz = []
    
    for item in raw_data:
        # 1. Get the parts
        question = str(item.get('question', '')).replace('$', '').replace('\\', '')
        correct_txt = str(item.get('correct_answer', '')).replace('$', '').replace('\\', '')
        wrong_list = item.get('wrong_answers', [])
        explanation = str(item.get('explanation', ''))

        # 2. Clean up Wrong Answers
        clean_wrongs = []
        for w in wrong_list:
            w = str(w).replace('$', '').replace('\\', '')
            clean_wrongs.append(w)

        # 3. Ensure we have exactly 3 wrong answers (Pad or Cut)
        # If AI gave too few wrongs, add placeholders
        while len(clean_wrongs) < 3:
            clean_wrongs.append("None of the above")
        # If AI gave too many, keep only 3
        clean_wrongs = clean_wrongs[:3]

        # 4. Combine and Shuffle
        all_options = [correct_txt] + clean_wrongs
        random.shuffle(all_options)

        # 5. Find the Index (The Truth)
        try:
            # We calculate the index logically by looking for the text
            correct_index = all_options.index(correct_txt)
        except:
            correct_index = 0 # Fallback

        # 6. Build the Final Object for the App
        quiz_item = {
            "question": question,
            "options": all_options,        # The shuffled list
            "correct_indices": [correct_index], # The Calculated Index
            "explanation": explanation,
            "type": "single"
        }
        
        final_quiz.append(quiz_item)

    # 7. Quantity Limit
    return final_quiz[:target_count]

@app.route('/')
def home():
    return "Revisionary Server: Priyanshu"

@app.route('/generate-quiz', methods=['POST'])
@app.route('/generate_quiz', methods=['POST'])
def generate_quiz():
    if not client: return jsonify({"error": "Missing API Key"}), 500

    try:
        num_questions = int(request.form.get('count', '5'))
    except:
        num_questions = 5

    context_text = ""
    
    if 'pdf' in request.files:
        file = request.files['pdf']
        filename = file.filename.lower()
        if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
             return jsonify({"error": "Image AI updating. Use PDF."}), 400
             
        try:
            file.seek(0)
            reader = PyPDF2.PdfReader(file)
            limit = min(len(reader.pages), 20) # Read more pages for better context
            for i in range(limit):
                page_text = reader.pages[i].extract_text()
                if page_text: context_text += page_text + "\n"
            
            context_text = clean_text(context_text)
            if len(context_text) < 50: return jsonify({"error": "PDF empty."}), 400
            context_text = context_text[:15000]
        except:
            return jsonify({"error": "PDF Fail."}), 500

    elif request.form.get('topic'):
        context_text = request.form.get('topic')

    try:
        print(f"Asking Groq for {num_questions} questions...")

        # --- NEW PROMPT: SEPARATE CORRECT AND WRONG ---
        system_instructions = f"""
        You are an expert quiz generator.
        
        TASK: Generate exactly {num_questions} questions based on the text.
        
        CRITICAL RULES:
        1. **Math Accuracy**: If text implies "2 is irrational", assume "Root 2". Verify your math.
        2. **Format**: Do NOT put options together. Give me the 'correct_answer' and 'wrong_answers' separately.
        3. **Explanation**: Explain why 'correct_answer' is right.
        
        Output Format (JSON List):
        [
          {{
            "question": "Question Text",
            "correct_answer": "The Correct Text",
            "wrong_answers": ["Wrong 1", "Wrong 2", "Wrong 3"],
            "explanation": "Reasoning..."
          }}
        ]
        """

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": f"Context:\n{context_text}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.2, # Low temp = better logic
            max_tokens=4000
        )

        json_str = extract_json(chat.choices[0].message.content)
        data = json.loads(json_str)
        
        # --- PYTHON ASSEMBLY LINE ---
        final_data = assemble_quiz(data, num_questions)
        
        if not final_data: return jsonify({"error": "AI response empty."}), 500

        return jsonify(final_data)

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return jsonify({"error": "Server Error."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
    





