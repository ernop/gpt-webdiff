#!/usr/bin/env python3

# Global notes: never use docstrings. Never remove these - they are guides for future rewrites when I paste in the entire file.
import os
import sys
import subprocess
import hashlib
import difflib
import smtplib
import json
from email.mime.text import MIMEText
from datetime import datetime
import openai
import argparse
import re
from bs4 import BeautifulSoup
import time

CONFIG_FILE = 'config.json'
API_KEY_FILE = 'apikey.txt'
VALID_FREQUENCIES = ['minutely', 'daily', 'hourly', 'weekly']
LOG_FILE = 'gpt_diff.log'

def extract_text_from_html(html_content):
    return BeautifulSoup(html_content, 'html.parser').get_text(separator=' ', strip=True)

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()

def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

def send_email(job_name, url, summary, diff_text, to_email):
    config = load_config()
    subject = f"Changes detected for {job_name} at {url}"
    body = f"""
    <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h1 {{ color: #333; }}
                .summary {{ margin-bottom: 20px; }}
                .diff {{ font-family: monospace; white-space: pre; background: #f4f4f4; padding: 10px; border-radius: 5px; }}
                .job-details {{ margin-bottom: 20px; }}
                .job-details b {{ display: inline-block; width: 100px; }}
            </style>
        </head>
        <body>
            <h1>Changes Detected</h1>
            <div class="job-details">
                <p><b>Job:</b> {job_name}</p>
                <p><b>URL:</b> <a href="{url}">{url}</a></p>
            </div>
            <div class="summary">
                <h2>Summary:</h2>
                <p>{summary}</p>
            </div>
            <div class="diff">
                <h2>Diff:</h2>
                <pre>{diff_text}</pre>
            </div>
        </body>
    </html>
    """
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From'] = config['email']
    msg['To'] = to_email
    save_email_to_disk(job_name, subject, body)
    log_message(f"Sending Email: Subject: {subject}, Body: {body[:1000]}...")

    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = config['email']
    smtp_password = config['password']

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())
        server.quit()
        print(f"Email sent to {to_email}")
        log_message(f"Email sent to {to_email} for job {job_name}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        log_message(f"Failed to send email to {to_email} for job {job_name}: {e}")

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d-%H-%M-%S')}.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    subprocess.run(['wget', '-O', output_file, '--user-agent', user_agent, url])
    return output_file

def get_last_file(name):
    job_dir = f"data/{name}"
    if not os.path.exists(job_dir):
        return None, None

    files = sorted([f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))])
    if files:
        last_file = files[-1]
        last_run_time = datetime.strptime(last_file, f"{name}-%Y%m%d-%H-%M-%S.html").timestamp()
        return os.path.join(job_dir, last_file), last_run_time
    return None, None

def compare_files(file1, file2):
    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        return ''.join(difflib.unified_diff(f1.readlines(), f2.readlines()))

def summarize_diff(diff_text, html_content):
    openai.api_key = load_apikey()
    context_text = extract_text_from_html(html_content)

    # Truncate the diff_text and context_text to fit within the allowed limit
    max_length = 1048576  # Maximum allowed length
    combined_text = f"Diff:\n{diff_text}\n{context_text}"[:10000]

    # Ensure the combined text is within the limit
    if len(combined_text) > max_length:
        combined_text = combined_text[:max_length]

    print(f"Sending to OpenAI for summarization:\n{combined_text[:500]}...")  # Print the first 500 characters for brevity

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Summarize the following changes detected in a webpage, mainly focusing on the human-meaningful changes rather than CSS or javascript ones. Provide a one-line summary of the likely reason and meaning for each of the relevant changes. Then break them down into conceptual groups and give a detailed summary of each. What follows are the line-by-line diffs, and then the full context of the page:\n\t{combined_text}"}
        ],
        max_tokens=1500
    )
    return response.choices[0].message['content'].strip()

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def add_job(name, url, frequency):
    if not re.match(r'^[a-zA-Z0-9-]+$', name):
        print(f"Error: Invalid job name: name must be alphanumeric.")
        sys.exit(1)
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not is_valid_url(url):
        print("Error: Invalid URL format.")
        sys.exit(1)
    if frequency not in VALID_FREQUENCIES:
        print(f"Error: Invalid frequency, must be 'hourly', 'daily', 'weekly', 'minutely'")
        sys.exit(1)

    cron_entry = f"{frequency} {name} {url}\n"
    with open('.gptcron', 'a') as f:
        f.write(cron_entry)
    print(f"Job '{name}' added successfully.")
    log_message(f"Job added: {name}, {url}, {frequency}")

def log_message(message):
    with open(LOG_FILE, 'a') as log_file:
        msg=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n"
        print(msg)
        log_file.write(msg)

def list_jobs():
    if not os.path.exists('.gptcron'):
        print("No jobs found.")
        return

    with open('.gptcron', 'r') as f:
        jobs = f.readlines()

    if not jobs:
        print("No jobs found.")
        return

    print("Current monitoring jobs:")
    for job in jobs:
        if job.strip() and not job.startswith('#'):
            print(job.strip())

def run_job(name, url):
    last_file, _ = get_last_file(name)
    latest_file = download_url(url, name)
    changes_detected = False

    if last_file:
        diff_text = compare_files(last_file, latest_file)
        if diff_text:
            changes_detected = True
            with open(latest_file, 'r') as f:
                html_content = f.read()
            log_message(f"Detected changes for job {name} at {url}")
            summary = summarize_diff(diff_text, html_content)
            send_email(name, url, summary, diff_text, load_config()['email'])

    return changes_detected

def parse_frequency(frequency):
    return {'hourly': 3600, 'daily': 86400, 'weekly': 604800, 'minutely':59}[frequency]

def check_cron():
    now = time.time()
    total_jobs = 0
    jobs_with_changes = 0
    emails_sent = 0
    emails_failed = 0

    if os.path.exists('.gptcron'):
        with open('.gptcron', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.split()
                    #~ import ipdb;ipdb.set_trace()
                    if len(parts) >= 3:
                        total_jobs += 1
                        frequency, name, url = parts[0], parts[1], parts[2]
                        _, last_run_time = get_last_file(name)
                        if last_run_time is None:
                            last_run_time = 0
                        next_run_time = last_run_time + parse_frequency(frequency)

                        if now >= next_run_time:
                            log_message(f"Running job: {name}")
                            changes_detected= run_job(name, url)
                            if changes_detected:
                                jobs_with_changes += 1
                                emails_sent += 1
                                log_message(f"Changes were detected for job: {name}")
                            else:
                                log_message(f"No changes detected for job: {name}")
                    else:
                        print('bad job entry:',line)

    log_message(f"Checked cron jobs. Total: {total_jobs}, Changes: {jobs_with_changes}, Emails Sent: {emails_sent}, Emails Failed: {emails_failed}")

def setup_argparse():
    parser = argparse.ArgumentParser(description='GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: add <name> <URL> <frequency>')
    add_parser.add_argument('name', type=str, help='Alphanumeric label for this job')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('frequency', type=str, choices=VALID_FREQUENCIES, help='Frequency to check the URL (e.g., daily, hourly, weekly)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name> <URL>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')
    run_parser.add_argument('url', type=str, help='URL to monitor')

    subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs.')
    subparsers.add_parser('list', help='List all monitoring jobs.')

    return parser

if __name__ == "__main__":
    try:
        parser = setup_argparse()
        args = parser.parse_args()
        log_message(f"Command called: {args.command}")

        if args.command == "add":
            add_job(args.name, args.url, args.frequency)
        elif args.command == "run":
            run_job(args.name, args.url)
        elif args.command == "check_cron":
            check_cron()
        elif args.command == "list":
            list_jobs()
        elif args.command == "remove":
            remove_job(args.name)
        else:
            parser.print_help()
    except Exception as e:
        log_message(f"Unexpected error: {e}")
        raise
