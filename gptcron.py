#!/usr/bin/env python3
import argparse
import difflib
import hashlib
import html
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText

import openai
from bs4 import BeautifulSoup, Comment
from openai import OpenAI

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
print('changing to:', script_dir)
os.chdir(script_dir)

VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']

def setup_argparse():
    parser = argparse.ArgumentParser(description='GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: `add <URL> <name, if missing will be filled in by gpt4o.> [weekly|daily|hourly|minutely <default weekly>]` or `add <URL> [name, if missing will be filled in by gpt4o.] [weekly|daily|hourly|minutely <default weekly>]`')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('name', type=str, nargs='?', help='Alphanumeric label for this job')
    add_parser.add_argument('frequency', type=str, nargs='?', choices=VALID_FREQUENCIES, default='daily', help='Frequency to check the URL (e.g weekly|daily|hourly|minutely)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    email_me_gptcron = subparsers.add_parser('email-backup', help='Email me the backup of .gptcron for safekeeping. Usage: email-backup.')

    check_parser = subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs.')
    check_parser.add_argument('force', type=str, nargs='?', help='Force override & trigger debugging.')

    list_parser = subparsers.add_parser('list', help='List all monitoring jobs.')
    list_parser.add_argument('--sort_by', choices=['date', 'url', 'name'], help='Sort jobs by date, url, or name')

    remove_parser = subparsers.add_parser('remove', help='Remove a job. Usage: remove <name>')
    remove_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    save_parser = subparsers.add_parser('save_sorted', help='Save sorted jobs to a file. Usage: save_sorted --sort_by <sort_by>')
    save_parser.add_argument('--sort_by', choices=['date', 'url', 'name'], required=True, help='Sort jobs by date, url, or name')

    inc_freq_parser = subparsers.add_parser('inc_frequency', help='Increase the frequency of a job. Usage: inc_frequency <name>')
    inc_freq_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    dec_freq_parser = subparsers.add_parser('dec_frequency', help='Decrease the frequency of a job. Usage: decrease_frequency <name>')
    dec_freq_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    debug_parser = subparsers.add_parser('reparse', help='Debug JSON parsing by dropping into ipdb')
    debug_parser.add_argument('name', type=str, help='Alphanumeric label for the job to debug')

    return parser


def summarize_diff(diff_text, all_text, html_content, url, name):
    context_text = extract_text_from_html(html_content)

    loaded_prompt = open('prompt.txt').read().strip()

    prompt = f"""{loaded_prompt}
        Here is the full text of the current version of the page with the diff of changes since the previous version included.{all_text[:20000]}"

        Please provide your response in the following JSON format:
        {{
            "summary": "generate a text summary of the webpage. Use newlines to separate paragraphs covering all the main aspects of the page. Make sure to cover it broadly.",
            "brief summary": "a one-sentence, pure text summary of the changes. This is for use within an email subject line, so it cannot be very long.",
            "score": your_score_here (integer from 1 to 10),
        }}
    """
    client = OpenAI(api_key=load_apikey())

    response = client.chat.completions.create(model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a helpful assistant which always returns json."},
        {"role": "user", "content": prompt}
    ],
    max_tokens=3500)

    response_text = response.choices[0].message.content.strip()
    unique_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(url.encode()).hexdigest()}"

    raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_bad.json"
    got = False
    response_json, got=attempt_to_deserialize_openai_json(response_text)


    if not got:
        summary = "Error parsing response"
        brief_summary = "Fail"
        score = 0
        raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_bad.json"
        with open(raw_response_filename, 'w') as f:
            f.write(response_text)
        print("ERROR")
        return "","",""
    os.makedirs('openai_responses', exist_ok=True)

    raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_okay.json"
    got = True
    summary, score, brief_summary = rip(response_json)

    with open(raw_response_filename, 'w') as f:
        f.write(response_text)
    return summary, score, brief_summary

def rip(response_json):
    try:
        summary = response_json['summary']
        score = int(response_json['score'])
        brief_summary = response_json['brief summary']
    except:
        print(response_json)
    return summary, score, brief_summary


def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

#email a copy of the .gptcron file to the user in settings.
def email_me_gptcron():
    now=datetime.now()
    subject=f"Backup of .gptcron, as of {now.year}/{now.month}/{now.day}"
    with open('.gptcron', 'r') as f:
        lines = f.readlines()
    body='<br>\n'.join(lines)
    to_email= load_config()['to_email']
    inner_send_email(subject, body,to_email)

def create_email_content(job_name, url, brief_summary, summary, diff_text, score):
    escaped_diff_text = html.escape(diff_text)
    formatted_summary = summary.replace('\n', '<br>')
    subject = f"GPT-diff | {job_name} | Score: {score} | {brief_summary}"

    with open('email_body_template.txt', 'r') as body_file:
        body_template = body_file.read().strip()

    body = body_template.format(
        job_name=job_name,
        url=url,
        summary=formatted_summary,
        diff_text=escaped_diff_text,
        brief_summary=brief_summary
    )

    return subject, body

def create_summary_email_content(job_name, url, brief_summary, summary):
    subject = f"GPT-diff | New job added: {job_name} | {brief_summary}"
    with open('summary_email_body_template.txt', 'r') as body_file:
        body_template = body_file.read().strip()

    body = body_template.format(
        job_name=job_name,
        url=url,
        summary=summary,
        brief_summary=brief_summary
    )

    return subject, body

def send_email(job_name, subject, body, to_email):
    save_email_to_disk(job_name, subject, body)
    log_message(f"Sending Email: Subject: {subject}, Body: {body[:1000]}...")
    inner_send_email(subject, body, to_email)
    print(f"Email sent to {to_email}")
    log_message(f"Email sent to {to_email} for job {job_name}")

def inner_send_email(subject, body, to_email):
    config = load_config()
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From'] = config['from_email']
    msg['To'] = to_email
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = config['login_email']
    smtp_password = config['password']

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")
        log_message(f"Failed to send email to {to_email}: {e}")



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
        msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}"
        print(msg)
        log_file.write(msg+'\n')

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

    attempt_to_deserialize_openai_json(raw_text)


def summarize_page(context_text, url, name):

    prompt = f"""Please provide a summary of the page content following, using the following JSON format:
        {{
            "summary": "[your_summary_here including all relevant sections, with specific details.]",
            "brief summary": "a one-sentence, pure text summary of the entire webpage and what it is all about.",
            "score": [your_score_here (integer from 1 to 10) for how globally relevant you think this page is, and how interesting you think it is.],
        }}

        Here is the content to base this JSON upon:

        {context_text}
    """
    client = OpenAI(api_key=load_apikey())
    response = client.chat.completions.create(model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a helpful assistant which always returns json."},
        {"role": "user", "content": prompt}
    ],
    max_tokens=3500)

    response_text = response.choices[0].message.content.strip()
    unique_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(url.encode()).hexdigest()}"

    raw_response_filename = f"openai_responses/{name}_{unique_id}_summary.json"
    got = False
    response_json, got= attempt_to_deserialize_openai_json(response_text)
    if not got:
        print("bad")
        return "",""
    summary, score, brief_summary = rip(response_json)
    raw_response_filename = f"openai_responses/{name}_{unique_id}_summary_okay.json"
    return summary, brief_summary


def parse_cron_file():
    jobs = []
    if not os.path.exists('.gptcron'):
        return jobs

    with open('.gptcron', 'r') as f:
        lines = f.readlines()

    for line in lines:
        if line.strip() and not line.startswith('#'):
            parts = line.split()
            if len(parts) >= 3:
                frequency = parts[0]
                name = parts[1]
                url = parts[2]
                date_added = parts[3] if len(parts) > 3 else "00000000000000"
                jobs.append({"frequency": frequency, "name": name, "url": url, "date_added": date_added})
    return jobs

def backup_cron_file():
    if not os.path.exists('.gptcron'):
        return
    os.makedirs('gptcron_backups', exist_ok=True)
    backup_file = os.path.join('gptcron_backups', f"gptcron_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy('.gptcron', backup_file)
    log_message(f"Backup created: {backup_file}")

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

#reutrns changed / new lines, and all text subsequently.
def compare_files(html1, html2):
    def extract_text(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            return soup.get_text(separator='\n', strip=True)

    old_lines = extract_text(html1).splitlines()
    new_lines = extract_text(html2).splitlines()

    differ = difflib.Differ()
    diff = list(differ.compare(old_lines, new_lines))

    diff_lines=[]
    all_lines=[]
    for line in diff:
        line=line.strip()
        if not line:
            continue
        all_lines.append(line)
        if line.startswith('  '):
            pass
        elif line.startswith('- '):
            diff_lines.append(line.replace("+ ","ADDED: ",1))
        elif line.startswith('+ '):
            diff_lines.append(line.replace("- ","REMOVED: ",1))

    diff_text = '\n'.join(diff_lines)
    all_text= '\n'.join(all_lines)


    if diff_text:
        print(diff_text)
        #~ import ipdb; ipdb.set_trace()

    return diff_text, all_text

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d-%H-%M-%S')}.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    subprocess.run(['wget', '-O', output_file, '--user-agent', user_agent, url])
    return output_file

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
VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']

def gpt_generate_job_names(url, text):
    openai.api_key = load_apikey()
    short_text=text[:1000]
    prompt=f"""I would like to create a short alphanumeric name (also including - for spaces bewteen words) for a webpage which has content given below.
    Let's think of some reasonable options. Our goals are simplicity, directness, making sure the context makes sense,etc. For example, if the url was http://nytimes.com and the content was: 'The New York Times - Breaking News, US News, World News and Videos Skip to content Skip to site index SKIP ADVERTISEMENT U.S. International Canada Today's Paper U.S. Sections U.S. Politics New York California Education Health Obituaries Science Climate Weather Sports Business Tech The Upshot The Magazine U.S. Politics 2024 Elections ' you should return the option: 'new-york-times'. Keep it simple.  That's because the hostname part of the URL is very important; that tells you what domain / page we are really looking at. The contents and remainder of the URL can also be used to hint at the result that is best.

    In this case, we are looking at the following URL: {url} which has this initial content
    {text}.

    Please return JUST the name you suggest, simplest form possible, max 4 words or so, as a json string like this: {{result: "<your result>"}}.
    """
    client = OpenAI(api_key=load_apikey())
    
    
    response = client.chat.completions.create(model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant which always returns json."},
                {"role": "user", "content": prompt}
        ],
        max_tokens=200)
    
    res = response.choices[0].message.content.strip()
    th, got = attempt_to_deserialize_openai_json(res)
    if not got:
        return ""
    jobname=th['result']
    if not re.match(r'^[a-zA-Z0-9-]+$', jobname):
        print(f"Error: Invalid job name: name must be alphanumeric.")
        sys.exit(1)
    return jobname

def get_gpt_name(url):
    latest_file = download_url(url, name="_no-name-yet")
    with open(latest_file, 'r', encoding='utf-8') as file:
        html_content = file.read()
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator = ' ', strip=True)
        response = gpt_generate_job_names(url, text_content)
        return response

def run_job(name):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)

    if not job:
        print(f"No job found with the name {name}")
        return False

    url = job["url"]
    metadata = load_metadata()
    last_successful_time = metadata.get(name, {}).get("last_successful_time", None)
    latest_file = download_url(url, name)
    changes_detected = False

    if last_successful_time:
        # Compare with the last successful file
        job_dir = f"data/{name}"
        files = sorted([f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))])
        last_successful_file = next((f for f in files if datetime.strptime(f, f"{name}-%Y%m%d-%H-%M-%S.html").timestamp() > last_successful_time), files[0])
        diff_text, all_text = compare_files(os.path.join(job_dir, last_successful_file), latest_file)

        if diff_text:
            print(diff_text)
            with open(latest_file, 'r') as f:
                html_content = f.read()
            log_message(f"Detected changes for job {name} at {url}")

            summary, score, brief_summary = summarize_diff(diff_text, all_text,  html_content, url, name)
            if not summary or not score or not brief_summary:
                return

            output_json = {
                "job_name": job["name"],
                "url": url,
                "summary": summary,
                "diff_text": diff_text,
                "score": score
            }

            if (last_successful_time is None and score > 0) or score >= 5:
                subject, body = create_email_content(job["name"], url, brief_summary, summary, diff_text, score)
                send_email(job["name"], subject, body, load_config()['to_email'])
                metadata[name] = {"last_successful_time": time.time()}
                changes_detected=True
                save_metadata(metadata)
            else:
                log_message(f"Score {score} below threshold for job {name}. Email not sent.")
        else:
            log_message(f"No changes detected for job: {name}")

    else: # First-time check: summarize the entire page
        with open(latest_file, 'r') as f:
            html_content = f.read()
        context_text = extract_text_from_html(html_content)
        log_message(f"First-time check for job {name} at {url}")
        if context_text=='':
            summary, brief_summary='',''
            log_message(f"First-time check for job {name} at {url} got no data from the page.")
        else:
            summary, brief_summary = summarize_page(context_text, url, name)
            subject, body = create_summary_email_content(job["name"], url, brief_summary, summary)
            send_email(job["name"], subject, body, load_config()['to_email'])
            changes_detected=True
            metadata[name] = {"last_successful_time": time.time()}
            save_metadata(metadata)

    return changes_detected

def add_job(name, url, frequency):

    if not name:
        name= get_gpt_name(url)
    if frequency==None:
        frequency='weekly'

    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not is_valid_url(url):
        print("Error: Invalid URL format.")
        sys.exit(1)
    if frequency not in VALID_FREQUENCIES:
        print(f"Error: Invalid frequency, must be 'hourly', 'daily', 'weekly', 'minutely'")
        sys.exit(1)

    jobs = parse_cron_file()
    if any(job['name'] == name for job in jobs):
        print(f"Error: A job with the name '{name}' already exists.")
        return

    backup_cron_file()
    cron_entry = f"{frequency} {name} {url} {datetime.now().strftime('%Y%m%d%H%M%S')}\n"
    with open('.gptcron', 'a') as f:
        f.write(cron_entry)
    print(f"Job '{name}' added successfully.")
    log_message(f"Job added: {name}, {url}, {frequency}")

def remove_job(name):
    jobs = parse_cron_file()
    backup_cron_file()
    with open('.gptcron', 'w') as f:
        for job in jobs:
            if job["name"] != name:
                f.write(f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n")
            else:
                log_message(f"Job removed: {job['name']}")

    print(f"Job '{name}' removed successfully.")

def change_frequency(name, direction):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)
    if not job:
        print(f"No job found with the name {name}")
        return

    current_index = VALID_FREQUENCIES.index(job["frequency"])
    num_dir = -1 if direction == 'increase' else 1
    new_index = current_index + num_dir

    if new_index < 0 or new_index >= len(VALID_FREQUENCIES):
        print(f"Error: Cannot change frequency. Current frequency is '{job['frequency']}' and no {'lower' if direction == 'decrease' else 'higher'} frequency available.")
        return

    new_frequency = VALID_FREQUENCIES[new_index]
    job["frequency"] = new_frequency
    backup_cron_file()

    with open('.gptcron', 'w') as f:
        for j in jobs:
            f.write(f"{j['frequency']} {j['name']} {j['url']} {j['date_added']}\n")

    print(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}' successfully.")
    log_message(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}'")

def list_jobs(sort_by=None):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    if sort_by == "date":
        jobs.sort(key=lambda x: x["date_added"])
    elif sort_by == "url":
        jobs.sort(key=lambda x: x["url"].split('//')[-1])
    elif sort_by == "name":
        jobs.sort(key=lambda x: x["name"].lower())

    max_lengths = [max(len(str(job[key])) for job in jobs) for key in ["frequency", "name", "url", "date_added"]]

    print("Current monitoring jobs:")
    print(f"{'Frequency'.ljust(max_lengths[0])}  {'Name'.ljust(max_lengths[1])}  {'URL'.ljust(max_lengths[2])}  {'Date Added'.ljust(max_lengths[3])}")
    print("=" * (sum(max_lengths) + 6))
    for job in jobs:
        print(f"{job['frequency'].ljust(max_lengths[0])}  {job['name'].ljust(max_lengths[1])}  {job['url'].ljust(max_lengths[2])}  {job['date_added'].ljust(max_lengths[3])}")

def save_sorted_jobs(sort_by):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    if sort_by == "date":
        jobs.sort(key=lambda x: x["date_added"])
    elif sort_by == "url":
        jobs.sort(key=lambda x: x["url"].split('//')[-1])
    elif sort_by == "name":
        jobs.sort(key=lambda x: x["name"])

    backup_cron_file()
    with open('.gptcron', 'w') as f:
        for job in jobs:
            f.write(f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n")

    print(f"Jobs sorted by {sort_by} and saved back to .gptcron")
    log_message(f"Jobs sorted by {sort_by} and saved back to .gptcron")


def parse_frequency(frequency):
    return {'hourly': 3600, 'daily': 86400, 'weekly': 604800, 'minutely': 59, 'monthly': 2592000}[frequency]

def check_cron(force = False):
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
                    if len(parts) >= 3:
                        total_jobs += 1
                        frequency, name, url = parts[0], parts[1], parts[2]
                        _, last_run_time = get_last_file(name)
                        if last_run_time is None:
                            last_run_time = 0
                        next_run_time = last_run_time + parse_frequency(frequency)

                        if (now >= next_run_time) or force:
                            log_message(f"Running job: {name}")
                            changes_detected = run_job(name)
                            if changes_detected:
                                jobs_with_changes += 1
                                emails_sent += 1
                                log_message(f"Changes were detected for job: {name}")
                            else:
                                log_message(f"No changes detected for job: {name}")
                        else:
                            fut=next_run_time - now
                            log_message(f"Not running job: {name} because its next run time is {fut:.0f}s in the future.")
                    else:
                        print('bad job entry:', line)

    log_message(f"Checked cron jobs. Total: {total_jobs}, Changes: {jobs_with_changes}, Emails Sent: {emails_sent}, Emails Failed: {emails_failed}")


def simple(s):
    return json.loads(s)

def try1(s):
    fix = s.strip('```json\n').strip('\n```')
    if fix.startswith('json'):
        fix = fix[4:]
    return json.loads(fix)

def try2(s):
    s = html.unescape(s)
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def try3(s):
    s = html.unescape(s)
    s = s.replace('\\\n', '')
    s = s.replace('\\', '')
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def attempt_to_deserialize_openai_json(response_text):
    got=False
    response_json=None
    response_text=response_text.replace('brief_summary','brief summary')

    for attempt in [simple, try1, try2, try3]:
        try:
            response_json = attempt(response_text)
            got=True
            break
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    if not got:
        print("bad tet.")
        return "",False
    return response_json,got



if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ["help", "-h", "--h"]:
            parser = setup_argparse()
            parser.print_help()
        else:
            parser = setup_argparse()
            args = parser.parse_args()
            log_message(f"Command called: {args.command}")
            if args.command == "add":
                name = args.name if args.name else ""
                frequency = args.frequency
                add_job(name, args.url, frequency)
            elif args.command == "run":
                run_job(args.name)
            elif args.command == "check_cron":
                check_cron(args.force)
            elif args.command == "list":
                list_jobs(args.sort_by)
            elif args.command == "remove":
                remove_job(args.name)
            elif args.command == "save_sorted":
                save_sorted_jobs(args.sort_by)
            elif args.command == "inc_frequency":
                change_frequency(args.name, "increase")
            elif args.command == "dec_frequency":
                change_frequency(args.name, "decrease")
            elif args.command == "reparse":
                debug_json_parsing(args.name)
            elif args.command=='email-backup':
                email_me_gptcron()
            else:
                parser.print_help()
    except Exception as e:
        log_message(f"Unexpected error: {e}")
        raise

