from flask import Flask, request, jsonify, send_from_directory, Response
import os, json, datetime, time, subprocess, queue, threading
from subprocess import Popen, PIPE

app = Flask(__name__, static_url_path='', static_folder='static')

MODELS_FILE = 'models.json'
CHAT_DIR = 'history'

def load_models():
    if os.path.exists(MODELS_FILE):
        with open(MODELS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_models(models):
    with open(MODELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(models, f, ensure_ascii=False)

@app.route('/api/models', methods=['GET', 'POST'])
def models_api():
    if request.method == 'GET':
        models = load_models()
        return jsonify(models)
    data = request.get_json()
    name = data.get('name')
    command = data.get('command')
    if not name or not command:
        return jsonify({'error': 'Missing name or command'}), 400
    models = load_models()
    models[name] = command
    save_models(models)
    return jsonify({'message': 'Model added', 'models': models})

@app.route('/api/new_chat', methods=['POST'])
def new_chat():
    data = request.get_json()
    model = data.get('model')
    if not model:
        return jsonify({'error': 'Missing model parameter'}), 400
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    dir_path = os.path.join(CHAT_DIR, model, today)
    os.makedirs(dir_path, exist_ok=True)
    # Check if an empty session exists (title empty and messages empty)
    session_files = [f for f in os.listdir(dir_path) if f.endswith('.json')]
    session_files.sort(key=lambda x: int(x.replace('.json','')), reverse=True)
    for sf in session_files:
        session_path = os.path.join(dir_path, sf)
        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
        except:
            session_data = {"title": "", "messages": []}
        if session_data.get("messages", []) == []:
            return jsonify({'session_id': session_path})
    # No empty session found; create a new one.
    timestamp = int(time.time())
    session_file = os.path.join(dir_path, f'{timestamp}.json')
    with open(session_file, 'w', encoding='utf-8') as f:
        json.dump({"title": "", "messages": []}, f, ensure_ascii=False)
    return jsonify({'session_id': session_file})

import re  # add this import if not already present

@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    model = data.get('model')
    session_id = data.get('session_id')
    message = data.get('message')
    if not model or not session_id or not message:
        return jsonify({'error': 'Missing parameters'}), 400
    if os.path.exists(session_id):
        with open(session_id, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
    else:
        session_data = {"title": "", "messages": []}
    if session_data.get("title", "") == "" and len(session_data.get("messages", [])) == 0:
        session_data["title"] = " ".join(message.split()[:5])
    session_data.setdefault("messages", []).append({'sender': 'user', 'text': message})
    
    models = load_models()
    model_command = models.get(model)
    if not model_command:
        bot_response = "Model command not found."
        session_data["messages"].append({'sender': 'bot', 'text': bot_response})
        with open(session_id, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False)
        return jsonify({'response': bot_response})
    process = Popen(model_command.split(),
                               stdin=PIPE,
                               stdout=PIPE,
                               stderr=PIPE,
                               encoding='utf-8',
                               bufsize=0)
    process.stdin.write(message + "\n")
    process.stdin.flush()
    process.stdin.close()
    def generate():
        bot_response = ""
        q = queue.Queue()
    
        def stream_output():
            try:
                while True:
                # Read larger chunks to capture all output
                    chunk = process.stdout.read(15)
                    if not chunk:
                        break
                    for char in chunk:
                        q.put(char)
            finally:
                q.put(None)  # Signal end of stream
    
        t = threading.Thread(target=stream_output)
        t.start()
    
        try:
            while True:
                try:
                    char = q.get(timeout=10)  # Increased timeout
                    if char is None:
                        break
                    bot_response += char
                    yield char
                except queue.Empty:
                    if process.poll() is not None:
                        break
        finally:
            t.join()
            process.wait()
        # Handle remaining output after process exits
            remaining = process.stdout.read()
            if remaining:
                for char in remaining:
                    bot_response += char
                    yield char
        # Save final response
            session_data["messages"].append({'sender': 'bot', 'text': bot_response})
            with open(session_id, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False)
        print(bot_response)
    return Response(generate(), mimetype='text/plain; charset=utf-8')


@app.route('/api/chats', methods=['GET'])
def list_chats():
    model = request.args.get('model')
    if not model:
        return jsonify({'error': 'Missing model parameter'}), 400
    sessions = []
    model_dir = os.path.join(CHAT_DIR, model)
    if os.path.exists(model_dir):
        for date_dir in os.listdir(model_dir):
            full_date_dir = os.path.join(model_dir, date_dir)
            if os.path.isdir(full_date_dir):
                for session_file in os.listdir(full_date_dir):
                    if session_file.endswith('.json'):
                        session_path = os.path.join(full_date_dir, session_file)
                        try:
                            with open(session_path, 'r', encoding='utf-8') as f:
                                session_data = json.load(f)
                            title = session_data.get('title', '')
                        except:
                            title = ''
                        sessions.append({
                            'session_id': session_path,
                            'date': date_dir,
                            'timestamp': session_file.replace('.json', ''),
                            'title': title
                        })
    sessions.sort(key=lambda x: int(x['timestamp']), reverse=True)
    return jsonify(sessions)

@app.route('/api/chat_session', methods=['GET'])
def get_chat_session():
    session_id = request.args.get('session_id')
    if not session_id or not os.path.exists(session_id):
        return jsonify({'error': 'Session not found'}), 404
    with open(session_id, 'r', encoding='utf-8') as f:
        session_data = json.load(f)
    return jsonify(session_data.get('messages', []))

@app.route('/api/rename_chat', methods=['POST'])
def rename_chat():
    data = request.get_json()
    session_id = data.get('session_id')
    new_title = data.get('title')
    if not session_id or not os.path.exists(session_id) or new_title is None:
        return jsonify({'error': 'Missing parameters or session not found'}), 400
    with open(session_id, 'r', encoding='utf-8') as f:
        session_data = json.load(f)
    session_data["title"] = new_title
    with open(session_id, 'w', encoding='utf-8') as f:
        json.dump(session_data, f, ensure_ascii=False)
    return jsonify({'message': 'Chat renamed', 'title': new_title})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    os.makedirs(CHAT_DIR, exist_ok=True)
    app.run(debug=True)
