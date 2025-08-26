from flask import Flask, request, jsonify, send_from_directory
import json
import os

app = Flask(__name__, static_folder='html')

@app.route('/')
def index():
    return send_from_directory('html', 'editor.html')

@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('html', path)

@app.route('/save-json', methods=['POST'])
def save_json():
    data = request.get_json()
    fileName = data.get('fileName')
    fileData = data.get('data')

    if not fileName or not fileData:
        return jsonify({'status': 'error', 'message': 'Missing fileName or data'}), 400

    try:
        # Security measure: ensure the filename is safe
        if '..' in fileName or fileName.startswith('/'):
            raise ValueError("Invalid fileName")

        filePath = os.path.join('html', 'json', fileName)
        with open(filePath, 'w', encoding='utf-8') as f:
            json.dump(fileData, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)