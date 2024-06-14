import json
import os
import html
from datetime import datetime
from bs4 import BeautifulSoup

CONFIG_FILE = 'config.json'
LOG_FILE = 'gpt_diff.log'
API_KEY_FILE = 'apikey.txt'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()

def log_message(message):
    with open(LOG_FILE, 'a') as log_file:
        msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n"
        print(msg)
        log_file.write(msg)

def load_metadata():
    if not os.path.exists('job_metadata.json'):
        return {}
    with open('job_metadata.json', 'r') as f:
        return json.load(f)

def save_metadata(metadata):
    with open('job_metadata.json', 'w') as f:
        json.dump(metadata, f)

def extract_text_from_html(html_content):
    return BeautifulSoup(html_content, 'html.parser').get_text(separator=' ', strip=True)

def debug_json_parsing(job_name):
    import ipdb
    ipdb.set_trace()
    job_dir = f"openai_responses/"
    files = sorted([f for f in os.listdir(job_dir) if 'parsed_bad' in f and job_name in f])
    if not files:
        print(f"No failed response files found for job {job_name}")
        return

    last_failed_file = os.path.join(job_dir, files[-1])
    with open(last_failed_file, 'r') as f:
        raw_text = f.read()

    print(f"Debugging last failed response from {last_failed_file}")

    for attempt in [normal, magic, magic2, magic3]:
        try:
            response_json = attempt(raw_text)
            print("Parsed JSON:", response_json)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error parsing JSON with {attempt.__name__}: {e}")
