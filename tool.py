
import os
import random
import json
import logging
from pathlib import Path
from io import BytesIO

import pytesseract
from PIL import Image
from flask import Flask, request, render_template_string, send_file, redirect, url_for, flash
from werkzeug.utils import secure_filename

# --------------------------- Configuration --------------------------- #
UPLOAD_FOLDER = Path("uploads")
BANK_FILE = Path("question_bank.json")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "txt"}

# Heuristic keywords for classification
QUESTION_TYPES = {
    "LR": {
        "Strengthen": ["strengthen", "support"],
        "Weaken": ["weaken", "undermine"],
        "Assumption": ["assume", "assumption"],
        "Flaw": ["flaw", "error", "mistake"],
        "Inference": ["infer", "inference", "follows"],
        "Principle": ["principle"],
        "Parallel Reasoning": ["parallel"],
        "Paradox": ["paradox"],
        "Method of Reasoning": ["method of reasoning", "method"]
    },
    "RC": {
        "Main Point": ["main point", "primary purpose"],
        "Author's Attitude": ["author's attitude", "tone"],
        "Inference": ["infer", "inference"],
        "Function": ["function of"],
        "Detail": ["detail", "mention"],
        "Analogy": ["analogy"],
        "Structure": ["structure", "organized"]
    }
}
DEFAULT_STRUCTURE = {"LR": 25, "RC": 27}
# --------------------------------------------------------------------- #

# Initialize app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecret")
UPLOAD_FOLDER.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load or init bank
if BANK_FILE.exists():
    try:
        with open(BANK_FILE, 'r', encoding='utf-8') as f:
            bank = json.load(f)
    except json.JSONDecodeError:
        bank = []
else:
    bank = []

# --------------------------- Helpers --------------------------- #

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_image(image_stream):
    image = Image.open(image_stream)
    return pytesseract.image_to_string(image)


def classify_question(text):
    lc_text = text.lower()
    # Check LR types: first match wins
    for qtype, keywords in QUESTION_TYPES['LR'].items():
        if any(kw in lc_text for kw in keywords):
            return qtype
    # Check RC types
    for qtype, keywords in QUESTION_TYPES['RC'].items():
        if any(kw in lc_text for kw in keywords):
            return qtype
    return "Unknown"


def save_bank():
    with open(BANK_FILE, 'w', encoding='utf-8') as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)


def generate_exam_text(structure):
    selected = []
    for section, total in structure.items():
        types = list(QUESTION_TYPES[section].keys())
        section_questions = [q for q in bank if q['type'] in types]
        base, rem = divmod(total, len(types))
        counts = {t: base for t in types}
        for t in random.sample(types, rem):
            counts[t] += 1
        for qtype, cnt in counts.items():
            candidates = [q for q in section_questions if q['type'] == qtype]
            if len(candidates) < cnt:
                logging.warning(f"Not enough '{qtype}' questions: needed {cnt}, available {len(candidates)}")
            selected.extend(random.sample(candidates, min(cnt, len(candidates))))
    random.shuffle(selected)
    output = []
    for i, q in enumerate(selected, 1):
        output.append(f"Q{i} [{q['type']}] ({q['source']}):\n{q['text'].strip()}\n")
    return "\n".join(output)

# --------------------------- Routes --------------------------- #

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('files')
        if not files:
            flash("No files selected")
            return redirect(request.url)
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = UPLOAD_FOLDER / filename
                file.save(filepath)
                if filepath.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    text = extract_text_from_image(filepath)
                else:
                    text = filepath.read_text(encoding='utf-8')
                if not text.strip():
                    flash(f"Failed to extract text from {filename}")
                    continue
                qtype = classify_question(text)
                entry = {"text": text, "type": qtype, "source": filename}
                if not any(e['text'] == text for e in bank):
                    bank.append(entry)
                    flash(f"Ingested {filename} as {qtype}")
                else:
                    flash(f"Duplicate {filename}; skipped.")
        save_bank()
        return redirect(request.url)
    return render_template_string(
        '''
        <!doctype html>
        <title>LSAT Practice Uploader</title>
        <h1>Upload missed questions</h1>
        <form method="post" enctype="multipart/form-data">
          <input type="file" name="files" multiple>
          <input type="submit" value="Upload">
        </form>
        <p><a href="{{ url_for('exam') }}">Generate Exam</a></p>
        <ul>{% for msg in get_flashed_messages() %}<li>{{ msg }}</li>{% endfor %}</ul>
        '''
    )

@app.route('/exam')
def exam():
    exam_text = generate_exam_text(DEFAULT_STRUCTURE)
    buffer = BytesIO()
    buffer.write(exam_text.encode('utf-8'))
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='exam.txt',
        mimetype='text/plain'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
