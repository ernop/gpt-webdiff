#!/usr/bin/env python3
import argparse
import traceback
import difflib
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import smtplib
import sys
import tempfile
import time
import requests
from collections import Counter
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment
from openai import OpenAI
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Warning: anthropic package not installed. Claude models will not be available.")

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
os.chdir(script_dir)
API_KEY_FILE = 'apikey.txt'
CONFIG_FILE = 'config.json'
MIN_SCORE = 7
CRON_LOCK_FILE = '.gptcron.lock'

VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']

# Model configuration - defaults can be overridden in config.json
DEFAULT_MODEL = "claude-sonnet-4-5"
FALLBACK_MODEL = "gpt-4o"
MODEL = DEFAULT_MODEL  # Legacy variable for backward compatibility

LOG_FILE = 'log.log'


class EmailDeliveryError(RuntimeError):
    pass


outer_prompt="""
You will rate how significant a change is on a scale of 0-10.

You rate each change in the context of the focus of the page.

If the page is about US National news, then rate things within the scale of how important they are to the US nation.
10 would be things like an invasion, assassination etc
5 would be things like a new law,
2 would be things like a small incident, bad weather, funny story, etc.

If the page is about a specific small coffee shop, then the meaning of the scale changes. Within this domain,
10 means it's going out of business, new ownership
8 would be significant new hours, moving location, etc
5 would be daily specials changing, new types of food etc

IF the page is about a company,
10 means going out of business, or major lawsuit etc
9 might be a change of name
8 means the departure of a senior employee, dramatic share price rise, etc

You will be given a diff of the things that have changed in the page, and some other context.

You will then output your evaluation of the change and its score following the following format:



    {
        "brief summary":"summarize the change in a few words",
        "summary": "detailed summary of the changes",
        "score": 6
    }

Rules:
* you must be specific
* the summary section must use HTML output and bullet points, headers. Deliver very compact information, dense, full of details.

"""

email_body_template="""<html>
<head>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1, h2, h3 {{
            margin: 10px 0;
            padding: 0;
        }}
        .content-block {{
            margin: 15px 0;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 5px;
        }}
        .job-details b {{
            display: inline-block;
            width: 100px;
        }}
        .diff {{
            font-family: monospace;
            white-space: pre-wrap;
            background: #f4f4f4;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        .diff-added {{
            background-color: #e6ffed;
            color: #24292e;
        }}
        .diff-removed {{
            background-color: #ffeef0;
            color: #24292e;
        }}
        .comparison-list {{
            list-style-type: none;
            padding-left: 0;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
    <h1>Changes Detected</h1>
    <div class="content-block job-details">
        <h3>[[brief_summary]]</h3>
        <p><b>Job:</b> [[job_name]]</p>
        <p><b>URL:</b> <a href="[[url]]">[[url]]</a></p>
    </div>

    <div class="content-block">
        <h2>Summary:</h2>
        <div>[[summary]]</div>
    </div>
    <div class="content-block">
        <h2>Comparison Information:</h2>
        [[comparison_info]]
    </div>
    <div class="content-block">
        <h2>Diff:</h2>
        <div class="diff">
[[diff_text]]
        </div>
    </div>
</body>
</html>
"""

summary_email_body_template="""<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; }}
        h1 {{margin:5px; padding-left:0;}}
        h2 {{margin: 5px; padding-left:0;}}
        h3 {{margin: 5px; padding-left:0;}}
        .job-details {{ margin: 20px; padding:10px; }}
        .job-details b {{ display: inline-block; width: 100px; }}
        .summary {{ margin: 20px; padding: 10px; border-radius: 5px; }}
        .diff {{ font-family: monospace; white-space: pre; background: #f4f4f4; padding: 10px; border-radius: 5px; }}
        img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <h1>New Job Added</h1>
    <div class="job-details">
        <h3>[[brief_summary]]</h3>
        <h3>Job:</h3> [[job_name]]
        <h3>URL:</h3> <a href="[[url]]">[[url]]</a>
    </div>
    <h1>Summary:</h1>
    <div class="summary">
        [[summary]]
    </div>
</body>
</html>
"""



def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()


def get_model_config():
    config = load_config()
    default_model = config.get('default_model', DEFAULT_MODEL)
    fallback_model = config.get('fallback_model', FALLBACK_MODEL)
    openai_key = config.get('openai_api_key') or None
    if not openai_key and os.path.exists(API_KEY_FILE):
        openai_key = load_apikey()
    anthropic_key = config.get('anthropic_api_key') or None
    return {
        'default_model': default_model,
        'fallback_model': fallback_model,
        'openai_api_key': openai_key,
        'anthropic_api_key': anthropic_key
    }


def get_model_provider(model):
    model_name = model.lower()
    if 'claude' in model_name:
        return 'anthropic'
    if model_name.startswith(('gpt-', 'o1', 'o3', 'o4')):
        return 'openai'
    raise ValueError(f"Unsupported model '{model}'. Use a Claude, GPT, or OpenAI o-series model.")


def call_llm(prompt, system_prompt="You are a helpful assistant.", max_tokens=4096, response_format=None, model=None):
    config = get_model_config()

    if model is None:
        model = config['default_model']

    def try_call(model_name):
        provider = get_model_provider(model_name)
        if provider == 'anthropic':
            if not ANTHROPIC_AVAILABLE:
                raise Exception("Anthropic package not installed. Run: pip install anthropic")
            if not config['anthropic_api_key']:
                raise Exception("Anthropic API key not found in config.json")

            client = anthropic.Anthropic(api_key=config['anthropic_api_key'])

            # Claude doesn't support response_format parameter directly
            if response_format and response_format.get('type') == 'json_object':
                prompt_with_json = f"{prompt}\n\nIMPORTANT: Respond ONLY with valid JSON. No other text."
            else:
                prompt_with_json = prompt

            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt_with_json}]
            )
            if not response.content:
                raise RuntimeError("Anthropic returned an empty response")
            return response.content[0].text
        else:
            if not config['openai_api_key']:
                raise Exception("OpenAI API key not found in config.json or apikey.txt")

            client = OpenAI(api_key=config['openai_api_key'])

            is_reasoning_model = model_name.lower().startswith(('o1', 'o3', 'o4'))
            if is_reasoning_model:
                messages = [{
                    "role": "user",
                    "content": f"{system_prompt}\n\n{prompt}"
                }]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            kwargs = {
                'model': model_name,
                'messages': messages
            }
            if is_reasoning_model:
                kwargs['max_completion_tokens'] = max_tokens
            else:
                kwargs['max_tokens'] = max_tokens

            if response_format:
                kwargs['response_format'] = response_format

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("OpenAI returned an empty response")
            return content.strip()

    try:
        return try_call(model)
    except Exception as e:
        log_message(f"Primary model {model} failed: {str(e)}")

        fallback = config['fallback_model']
        if fallback and fallback != model:
            try:
                log_message(f"Trying fallback model: {fallback}")
                return try_call(fallback)
            except Exception as e2:
                log_message(f"Fallback model {fallback} also failed: {str(e2)}")
                raise RuntimeError(
                    f"Both primary ({model}) and fallback ({fallback}) models failed"
                ) from e2
        else:
            raise

def log_message(message):
    msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}"
    try:
        print(msg)
    except Exception:
        pass
    try:
        with open(LOG_FILE, 'a') as log_file:
            log_file.write(msg+'\n')
    except Exception as e:
        try:
            print(f"Could not write to {LOG_FILE}: {str(e)}")
        except Exception:
            pass

def load_metadata():
    if not os.path.exists('job_metadata.json'):
        return {}
    with open('job_metadata.json', 'r') as f:
        return json.load(f)

def save_metadata(metadata):
    atomic_write_text('job_metadata.json', json.dumps(metadata))


def atomic_write_text(path, content):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True
    )
    try:
        with os.fdopen(file_descriptor, 'w', encoding='utf-8') as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def write_cron_jobs(jobs):
    content = ''.join(
        f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n"
        for job in jobs
    )
    if os.path.exists('.gptcron'):
        with open('.gptcron', 'r', encoding='utf-8') as cron_file:
            for line_number, line in enumerate(cron_file, start=1):
                if not line.strip() or line.startswith('#'):
                    content += line
                    continue
                _, error = parse_cron_line(line, line_number)
                if error:
                    content += line
    atomic_write_text('.gptcron', content)


def parse_cron_line(line, line_number):
    parts = line.split()
    if len(parts) not in (3, 4):
        return None, f"Skipping malformed .gptcron line {line_number}: {line.rstrip()}"
    frequency, name, url = parts[:3]
    date_added = parts[3] if len(parts) == 4 else "00000000000000"
    if frequency not in VALID_FREQUENCIES:
        return None, f"Skipping .gptcron line {line_number}: invalid frequency '{frequency}'"
    if not is_safe_existing_job_name(name):
        return None, f"Skipping .gptcron line {line_number}: unsafe job name '{name}'"
    if not re.fullmatch(r'\d{14}', date_added):
        return None, f"Skipping .gptcron line {line_number}: invalid date '{date_added}'"
    return {
        "frequency": frequency,
        "name": name,
        "url": url,
        "date_added": date_added
    }, None

#email a copy of the .gptcron file to the user in settings.
def email_me_gptcron():
    if not os.path.exists('.gptcron'):
        print("No .gptcron file found. Add a job before requesting a backup.")
        return
    now=datetime.now()
    subject=f"Backup of .gptcron, as of {now.year}/{now.month}/{now.day}"
    with open('.gptcron', 'r') as f:
        lines = f.readlines()
    body='<br>\n'.join(lines)
    to_email= load_config()['to_email']
    inner_send_email(subject, body,to_email)


def setup_argparse():
    parser = argparse.ArgumentParser(description='gpt-diff: Monitor web pages for changes and get detailed email summaries of those changes.')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: `add <URL> [name] [weekly|daily|hourly|minutely|monthly <default daily>]`')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('name', type=str, nargs='?', help='Alphanumeric label for this job')
    add_parser.add_argument('frequency', type=str, nargs='?', choices=VALID_FREQUENCIES, default='daily', help='Frequency to check the URL (e.g weekly|daily|hourly|minutely)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    email_me_gptcron = subparsers.add_parser('email-backup', help='Email me the backup of .gptcron for safekeeping. Usage: email-backup.')

    check_parser = subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs.')
    check_parser.add_argument('force', type=str, nargs='?', choices=['force'], help='Run every job even when it is not due.')

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

    debug_parser = subparsers.add_parser('reparse', help='Retry parsing the latest invalid saved LLM response')
    debug_parser.add_argument('name', type=str, help='Alphanumeric label for the job to debug')

    search_parser = subparsers.add_parser('search', help='Search for jobs by name or URL. Usage: search <query>')
    search_parser.add_argument('query', type=str, help='Search query for job name or URL')

    bump_parser = subparsers.add_parser('bump', help='Increase the frequency of an existing job. Usage: bump <job_name>')
    bump_parser.add_argument('name', type=str, help='Name of the job to bump')

    unbump_parser = subparsers.add_parser('unbump', help='Decrease the frequency of an existing job. Usage: unbump <job_name>')
    unbump_parser.add_argument('name', type=str, help='Name of the job to unbump')

    test_parser = subparsers.add_parser('test', help='Test a job by forcing a comparison. Usage: test [job_name]')
    test_parser.add_argument('name', type=str, nargs='?', help='Name of the job to test (optional)')

    compare_wikis_parser = subparsers.add_parser('compare_wikis', help='Compare Grokipedia and Wikipedia pages for a given subject. Usage: compare_wikis <subject>')
    compare_wikis_parser.add_argument('subject', type=str, help='Subject/topic to compare between Grokipedia and Wikipedia')
    compare_wikis_parser.add_argument('--send-email', action='store_true', help='Send results via email instead of printing to console')

    return parser

def test_job(name=None):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    if name:
        job = next((job for job in jobs if job["name"] == name), None)
        if not job:
            print(f"No job found with the name {name}")
            return
        jobs_to_test = [job]
    else:
        import random
        jobs_to_test = [random.choice(jobs)]

    for job in jobs_to_test:
        print(f"Testing job: {job['name']}")
        changes_detected = run_job(job['name'])
        if changes_detected:
            print(f"Changes detected for job: {job['name']}. An email was sent.")
        else:
            print(f"No changes detected for job: {job['name']}. No email was sent.")

    print("Test completed.")

def fetch_page_content(url):
    try:
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        headers = {'User-Agent': user_agent}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def compare_wikis(subject, send_results_email=False):
    log_message(f"Starting wiki comparison for subject: {subject}")

    url_subject = quote(subject.replace(' ', '_'), safe='()_-')

    wikipedia_url = f"https://en.wikipedia.org/wiki/{url_subject}"

    grokipedia_urls = [
        f"https://grokipedia.com/page/{url_subject}",
        f"https://grokipedia.com/{url_subject}",
    ]

    print(f"Fetching Wikipedia page: {wikipedia_url}")
    wikipedia_content = fetch_page_content(wikipedia_url)

    if not wikipedia_content:
        print("Failed to fetch Wikipedia content")
        return

    # Try multiple Grokipedia URL patterns
    grokipedia_content = None
    grokipedia_url = None
    for url in grokipedia_urls:
        print(f"Trying Grokipedia URL: {url}")
        content = fetch_page_content(url)
        if content:
            grokipedia_content = content
            grokipedia_url = url
            print(f"Successfully fetched from: {url}")
            break

    if not grokipedia_content:
        print(f"Failed to fetch Grokipedia content from any known URL patterns.")
        print(f"Tried: {', '.join(grokipedia_urls)}")
        print("\nNote: Grokipedia was recently launched (Oct 2025). Please check the actual URL structure.")
        print("You can manually specify the correct URL by modifying the grokipedia_urls list in the compare_wikis function.")
        return

    # Extract text from HTML
    wikipedia_soup = BeautifulSoup(wikipedia_content, 'html.parser')
    grokipedia_soup = BeautifulSoup(grokipedia_content, 'html.parser')

    wikipedia_text = wikipedia_soup.get_text(separator=' ', strip=True)
    grokipedia_text = grokipedia_soup.get_text(separator=' ', strip=True)

    print(f"\nWikipedia content length: {len(wikipedia_text)} characters")
    print(f"Grokipedia content length: {len(grokipedia_text)} characters")

    # Prepare prompt for GPT comparison
    prompt = f"""Please provide a detailed comparison of these two encyclopedia pages about "{subject}".

WIKIPEDIA PAGE:
================================================================================
{wikipedia_text[:50000]}
================================================================================

GROKIPEDIA PAGE:
================================================================================
{grokipedia_text[:50000]}
================================================================================

Please analyze and explain:
1. What are the key differences in content between these two pages?
2. What information is present in one but missing in the other?
3. What are the differences in emphasis, tone, or perspective?
4. Are there any notable differences in how the subject is presented or framed?
5. Which page appears more comprehensive, and in what ways?
6. Are there any potential biases evident in either presentation?
7. What unique insights or information does each page provide?

Please provide a thorough, detailed analysis in HTML format with clear sections and bullet points.
Return your response in this JSON format:
{{
    "summary": "Your detailed HTML-formatted analysis here",
    "wikipedia_unique_points": "Key points only in Wikipedia",
    "grokipedia_unique_points": "Key points only in Grokipedia",
    "major_differences": "Most significant differences",
    "bias_assessment": "Assessment of any potential biases"
}}
"""

    print("\nSending comparison request to LLM...")

    try:
        response_text = call_llm(
            prompt=prompt,
            system_prompt="You are a helpful assistant that provides detailed, objective analysis of content differences.",
            response_format={"type": "json_object"},
            max_tokens=4096
        )
        response_json, got = attempt_to_deserialize_openai_json(response_text)

        if not got:
            print("Error: Failed to parse GPT response")
            print(response_text)
            return

        # Save the comparison to disk
        os.makedirs('wiki_comparisons', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        safe_subject = re.sub(r'[^a-zA-Z0-9_-]+', '_', subject).strip('_') or 'comparison'
        output_file = f"wiki_comparisons/{safe_subject}_{timestamp}.html"

        # Create HTML output
        html_output = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Wiki Comparison: {subject}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .section {{
            background-color: white;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        .urls {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .urls a {{
            color: #3498db;
            text-decoration: none;
        }}
        .urls a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Wikipedia vs Grokipedia Comparison</h1>
        <h2>Subject: {subject}</h2>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <div class="urls">
        <p><strong>Wikipedia:</strong> <a href="{wikipedia_url}" target="_blank">{wikipedia_url}</a></p>
        <p><strong>Grokipedia:</strong> <a href="{grokipedia_url}" target="_blank">{grokipedia_url}</a></p>
    </div>

    <div class="section">
        <h2>Detailed Analysis</h2>
        {response_json.get('summary', 'No summary available')}
    </div>

    <div class="section">
        <h2>Wikipedia Unique Points</h2>
        {response_json.get('wikipedia_unique_points', 'No data available')}
    </div>

    <div class="section">
        <h2>Grokipedia Unique Points</h2>
        {response_json.get('grokipedia_unique_points', 'No data available')}
    </div>

    <div class="section">
        <h2>Major Differences</h2>
        {response_json.get('major_differences', 'No data available')}
    </div>

    <div class="section">
        <h2>Bias Assessment</h2>
        {response_json.get('bias_assessment', 'No data available')}
    </div>
</body>
</html>
"""

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_output)

        print(f"\nComparison saved to: {output_file}")

        if send_results_email:
            config = load_config()
            subject_line = f"Wiki Comparison: {subject} (Wikipedia vs Grokipedia)"
            send_email("wiki_comparison", subject_line, html_output, config['to_email'])
            print("Comparison sent via email")
        else:
            print("\n" + "="*80)
            print("COMPARISON RESULTS")
            print("="*80)
            print(f"\nSubject: {subject}")
            print(f"Wikipedia URL: {wikipedia_url}")
            print(f"Grokipedia URL: {grokipedia_url}")
            print("\n" + "-"*80)
            print("DETAILED ANALYSIS:")
            print("-"*80)
            # Strip HTML for console display
            from html import unescape
            clean_summary = BeautifulSoup(response_json.get('summary', ''), 'html.parser').get_text()
            print(clean_summary)
            print("\n" + "-"*80)
            print("WIKIPEDIA UNIQUE POINTS:")
            print("-"*80)
            clean_wiki = BeautifulSoup(response_json.get('wikipedia_unique_points', ''), 'html.parser').get_text()
            print(clean_wiki)
            print("\n" + "-"*80)
            print("GROKIPEDIA UNIQUE POINTS:")
            print("-"*80)
            clean_grok = BeautifulSoup(response_json.get('grokipedia_unique_points', ''), 'html.parser').get_text()
            print(clean_grok)
            print("\n" + "-"*80)
            print("MAJOR DIFFERENCES:")
            print("-"*80)
            clean_diff = BeautifulSoup(response_json.get('major_differences', ''), 'html.parser').get_text()
            print(clean_diff)
            print("\n" + "-"*80)
            print("BIAS ASSESSMENT:")
            print("-"*80)
            clean_bias = BeautifulSoup(response_json.get('bias_assessment', ''), 'html.parser').get_text()
            print(clean_bias)
            print("\n" + "="*80)

        log_message(f"Wiki comparison completed for: {subject}")

    except Exception as e:
        error_msg = f"Error during comparison: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        log_message(error_msg)

def check_conformity(response_json):
    if not isinstance(response_json, dict):
        print(f"Expected a JSON object, got: {type(response_json)}")
        return False

    if 'brief summary' not in response_json and 'brief_summary' in response_json:
        response_json['brief summary'] = response_json.pop('brief_summary')

    required_keys = {'summary': str, 'brief summary': str, 'score': int}

    for key, expected_type in required_keys.items():
        if key not in response_json:
            print(f"Missing required key: {key}")
            print(f"and the json is::: {response_json}")
            return False
        if key == 'score' and isinstance(response_json[key], bool):
            print("Invalid type for score: expected a number, got bool")
            return False
        if not isinstance(response_json[key], expected_type):
            if key == 'score' and isinstance(response_json[key], (str, float)):
                try:
                    response_json[key] = int(float(response_json[key]))
                except ValueError:
                    print(f"Invalid type for {key}: expected {expected_type}, got {type(response_json[key])}")
                    return False
            else:
                print(f"Invalid type for {key}: expected {expected_type}, got {type(response_json[key])}")
                return False
    if not 0 <= response_json['score'] <= 10:
        print(f"Invalid score {response_json['score']}: expected a value from 0 to 10")
        return False
    return True


def summarize_diff(diff_text, all_text, html_content, url, name):
    context_text = extract_text_from_html(html_content)

    loaded_prompt = outer_prompt

    prompt = f"""{loaded_prompt}
        Page URL: {url}

        Current page context:
        ============
        {context_text[:12000]}
        ============

        Here is the full list of all lines added or removed in this time interval.  Your summary is relating to what the addition or removal of this content means; your summary is NOT about the lines that remained unchanged:
        ============

        {diff_text[:50000]}

        ============

    """

    response_text = call_llm(
        prompt=prompt,
        system_prompt="You are a helpful assistant that returns JSON responses.",
        response_format={"type": "json_object"},
        max_tokens=3500
    )

    unique_id = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{hashlib.md5(url.encode()).hexdigest()}"
    os.makedirs('openai_responses', exist_ok=True)
    response_json, got = attempt_to_deserialize_openai_json(response_text)
    if not got or not check_conformity(response_json):
        raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_bad.txt"
        with open(raw_response_filename, 'w', encoding='utf-8') as f:
            f.write(response_text)
        raise ValueError(f"LLM returned invalid change-summary JSON for job '{name}'")

    raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_okay.txt"
    summary, score, brief_summary = rip(response_json)


    with open(raw_response_filename, 'w', encoding='utf-8') as f:
        f.write("================PROMPT:==============\r\n\r\n")
        f.write(prompt)
        f.write("\r\n\r\n================RESPONSE:==============\r\n\r\n")
        f.write(response_text)
    return summary, score, brief_summary

def rip(response_json):
    try:
        summary = response_json['summary']
        score = int(response_json['score'])
        brief_summary = response_json['brief summary']
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid LLM response: {response_json}") from e
    return summary, score, brief_summary


def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"Subject: {subject}\n\n{body}")



def create_email_content(job_name, url, brief_summary, summary, diff_text, score, current_file, compared_files):
    def format_diff(diff):
        formatted = ""
        for line in diff.split('\n'):
            if line.startswith('ADDED:'):
                formatted += f'<span class="diff-added">{line}</span>\n'
            elif line.startswith('REMOVED:'):
                formatted += f'<span class="diff-removed">{line}</span>\n'
            else:
                formatted += line + '\n'
        return formatted

    escaped_diff_text = format_diff(html.escape(diff_text))
    formatted_summary = summary.replace('\n', '<br>')
    subject = f"gpt-diff | {job_name} | Score: {score} | {brief_summary}"

    current_date = datetime.fromtimestamp(os.path.getmtime(current_file)).strftime('%Y-%m-%d %H:%M:%S')

    if len(compared_files) == 2:
        old_date = datetime.fromtimestamp(os.path.getmtime(compared_files[0])).strftime('%Y-%m-%d %H:%M:%S')
        comparison_info = f"<p>Comparing current version (downloaded on {current_date}) with previous version (downloaded on {old_date}).</p>"
    else:
        comparison_info = f"<p>Comparing current version (downloaded on {current_date}) with multiple previous versions:</p><ul class='comparison-list'>"
        for file in compared_files:
            file_date = datetime.fromtimestamp(os.path.getmtime(file)).strftime('%Y-%m-%d %H:%M:%S')
            comparison_info += f"<li>Version downloaded on {file_date}</li>"
        comparison_info += "</ul>"

    # Use a different method to replace placeholders
    body = email_body_template.replace("[[job_name]]", html.escape(job_name))
    body = body.replace("[[url]]", html.escape(url, quote=True))
    body = body.replace("[[summary]]", formatted_summary)
    body = body.replace("[[diff_text]]", escaped_diff_text)
    body = body.replace("[[brief_summary]]", html.escape(brief_summary))
    body = body.replace("[[comparison_info]]", comparison_info)

    return subject, body

def create_summary_email_content(job_name, url, brief_summary, summary):
    subject = f"gpt-diff | New job added: {job_name} | {brief_summary}"

    body = summary_email_body_template.replace("[[job_name]]", html.escape(job_name))
    body = body.replace("[[url]]", html.escape(url, quote=True))
    body = body.replace("[[summary]]", summary)
    body = body.replace("[[brief_summary]]", html.escape(brief_summary))

    return subject, body

def send_email(job_name, subject, body, to_email):
    log_message(f"Sending Email: Subject: {subject}, Body: {body[:1000]}...")
    inner_send_email(subject, body, to_email)
    try:
        save_email_to_disk(job_name, subject, body)
    except Exception as e:
        log_message(f"Email was sent but its local archive could not be saved: {str(e)}")
    try:
        print(f"Email sent to {to_email}")
        log_message(f"Email sent to {to_email} for job {job_name}")
    except Exception:
        pass

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

    server = None
    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())
    except Exception as e:
        print(f"Failed to send email: {e}")
        log_message(f"Failed to send email to {to_email}: {e}")
        raise EmailDeliveryError(f"Failed to send email to {to_email}") from e
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception as e:
                log_message(f"SMTP cleanup failed after delivery attempt: {str(e)}")




def extract_text_from_html(html_content):
    return ' '.join(extract_visible_lines_from_html(html_content))


def extract_visible_lines_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup(['script', 'style', 'noscript', 'template']):
        element.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    lines = []
    for line in soup.get_text(separator='\n').splitlines():
        normalized_line = ' '.join(line.split())
        if normalized_line:
            lines.append(normalized_line)
    return lines

def debug_json_parsing(job_name):
    job_dir = "openai_responses"
    if not os.path.exists(job_dir):
        print("No saved LLM responses found.")
        return
    files = sorted([f for f in os.listdir(job_dir) if 'parsed_bad' in f and job_name in f])
    if not files:
        print(f"No failed response files found for job {job_name}")
        return

    last_failed_file = os.path.join(job_dir, files[-1])
    with open(last_failed_file, 'r') as f:
        raw_text = f.read()

    print(f"Reparsing last failed response from {last_failed_file}")
    response, got = attempt_to_deserialize_openai_json(raw_text)
    if got:
        print(json.dumps(response, indent=2))
    else:
        print("The response is still not valid JSON.")


def summarize_page(context_text, url, name, job):

    prompt = f"""Please provide a summary of the page content following, using the following JSON format:
        {{
            "summary": "[your_summary_here including all relevant sections, with specific details.]",
            "brief summary": "a one-sentence, pure text summary of the entire webpage and what it is all about.",
            "score": [your_score_here (integer from 1 to 10) for how globally relevant you think this page is, and how interesting you think it is.],
        }}

        Here is the content to base this JSON upon:

        {context_text}
    """

    response_text = call_llm(
        prompt=prompt,
        system_prompt="You are a helpful assistant which always returns JSON.",
        response_format={"type": "json_object"},
        max_tokens=3500
    )
    unique_id = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{hashlib.md5(url.encode()).hexdigest()}"
    os.makedirs('openai_responses', exist_ok=True)
    response_json, got = attempt_to_deserialize_openai_json(response_text)

    if not got or not check_conformity(response_json):
        raw_response_filename = f"openai_responses/{name}_{unique_id}_summary_bad.json"
        with open(raw_response_filename, 'w', encoding='utf-8') as f:
            f.write(response_text)
        raise ValueError(f"LLM returned invalid page-summary JSON for job '{job['name']}'")
    summary, score, brief_summary = rip(response_json)
    raw_response_filename = f"openai_responses/{name}_{unique_id}_summary_okay.json"
    with open(raw_response_filename, 'w', encoding='utf-8') as f:
        f.write(response_text)
    return summary, brief_summary


def parse_cron_file():
    jobs = []
    if not os.path.exists('.gptcron'):
        return jobs

    with open('.gptcron', 'r') as f:
        lines = f.readlines()

    for line_number, line in enumerate(lines, start=1):
        if line.strip() and not line.startswith('#'):
            job, error = parse_cron_line(line, line_number)
            if error:
                print(error)
            else:
                jobs.append(job)
    return jobs

def backup_cron_file():
    if not os.path.exists('.gptcron'):
        return
    os.makedirs('gptcron_backups', exist_ok=True)
    backup_file = os.path.join(
        'gptcron_backups',
        f"gptcron_backup_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    )
    shutil.copy('.gptcron', backup_file)
    log_message(f"Backup created: {backup_file}")


def get_snapshot_versions(name):
    job_dir = f"data/{name}"
    if not os.path.exists(job_dir):
        return []

    snapshots = []
    formats = [
        f"{name}-%Y%m%d-%H-%M-%S-%f.html",
        f"{name}-%Y%m%d-%H-%M-%S.html"
    ]
    for filename in os.listdir(job_dir):
        path = os.path.join(job_dir, filename)
        if not os.path.isfile(path):
            continue
        snapshot_time = None
        for filename_format in formats:
            try:
                snapshot_time = datetime.strptime(filename, filename_format)
                break
            except ValueError:
                continue
        if snapshot_time is not None:
            snapshots.append((snapshot_time, path))
    snapshots.sort(key=lambda snapshot: snapshot[0])
    return snapshots


def get_last_file(name):
    snapshots = get_snapshot_versions(name)
    if snapshots:
        snapshot_time, last_file = snapshots[-1]
        return last_file, snapshot_time.timestamp()
    return None, None


#returns changed / new lines, and all text subsequently.
def compare_files(html1, html2):
    def extract_text(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return extract_visible_lines_from_html(f.read())

    old_lines = extract_text(html1)
    new_lines = extract_text(html2)
    differ = difflib.Differ()

    diff = differ.compare(old_lines, new_lines)
    diff_lines=[]
    all_lines=[]
    for line in diff:
        if not line[2:].strip():
            continue
        content = line[2:].strip()
        all_lines.append(content)

        if line.startswith('  '):
            pass
        elif line.startswith('- '):
            diff_lines.append(f"REMOVED: {content}")
        elif line.startswith('+ '):
            diff_lines.append(f"ADDED: {content}")

    diff_text = '\r\n'.join(diff_lines)
    all_text= '\r\n'.join(all_lines)
    return diff_text, all_text

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d-%H-%M-%S-%f')}.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

    try:
        # Use requests library instead of wget for better cross-platform compatibility
        headers = {'User-Agent': user_agent}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(response.text)

        log_message(f"Downloaded {url} to {output_file}")
        return output_file
    except requests.exceptions.RequestException as e:
        log_message(f"Error downloading {url}: {e}")
        raise

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


def normalize_url(url):
    if not url.startswith(('http://', 'https://')):
        return 'http://' + url
    return url


def is_valid_job_name(name):
    return bool(name and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', name))


def is_safe_existing_job_name(name):
    return bool(
        name
        and name not in ('.', '..')
        and '/' not in name
        and '\\' not in name
        and not any(character.isspace() for character in name)
    )


def gpt_generate_job_names(url, text, exclusions):
    short_text=text[:1000]
    exclusion_text=""
    if exclusions:
        exclusion_text ="Additionally, this name is already taken, so please do not use it and instead use another one: %s\r\n"%str(exclusions)

    prompt=f"""I would like to create a short alphanumeric name (also including - for spaces bewteen words) for a webpage which has content given below.
    Let's think of some reasonable options. Our goals are simplicity, directness, making sure the context makes sense,etc. For example, if the url was http://nytimes.com and the content was: 'The New York Times - Breaking News, US News, World News and Videos Skip to content Skip to site index SKIP ADVERTISEMENT U.S. International Canada Today's Paper U.S. Sections U.S. Politics New York California Education Health Obituaries Science Climate Weather Sports Business Tech The Upshot The Magazine U.S. Politics 2024 Elections ' you should return the option: 'new-york-times'. Keep it simple.  That's because the hostname part of the URL is very important; that tells you what domain / page we are really looking at. The contents and remainder of the URL can also be used to hint at the result that is best.

    Good names are short, and include both the topic being discussed, and if it's generic, also include perhaps the URL or source of the information.
    {exclusion_text}

    In this case, we are looking at the following URL: {url} which has this initial content
    {text}.

    Please return JUST the name you suggest, simplest form possible, max 4 words or so, as a json string like this: {{result: "<your result>"}}.
    """

    res = call_llm(
        prompt=prompt,
        system_prompt="You are a helpful assistant which always returns JSON.",
        response_format={"type": "json_object"},
        max_tokens=200
    )
    response, got = attempt_to_deserialize_openai_json(res)
    if not got:
        return ""
    jobname = response['result']
    if not is_valid_job_name(jobname):
        raise ValueError("Generated job name must contain only letters, numbers, hyphens, or underscores")
    return jobname

#also checks that the name is unique.
def get_gpt_name(url, exclusions = None):
    jobs = parse_cron_file()

    def is_valid_name(name):
        return name and name.strip()

    def is_name_duplicate(name):
        return any(job['name'] == name for job in jobs)

    try:
        latest_file = download_url(url, name="_no-name-yet")
        with open(latest_file, 'r', encoding='utf-8') as file:
            html_content = file.read()
            soup = BeautifulSoup(html_content, 'html.parser')
            text_content = soup.get_text(separator=' ', strip=True)
            suggested_name = gpt_generate_job_names(url, text_content, exclusions)

            if not is_valid_name(suggested_name):
                raise ValueError(f"Generated name '{suggested_name}' is invalid.")

            if is_name_duplicate(suggested_name):
                #if we already have been excluded from a name, and yet we generated it again or another existing one too, just fail.
                if exclusions:
                    raise ValueError(f"Generated name '{suggested_name}' already exists.")
                else:
                    #try one time to generate another one, overcoming the last duplicate
                    return get_gpt_name(url, suggested_name)
            return suggested_name
    except Exception as e:

        raise ValueError(f"Failed to generate a valid job name for {url}: {str(e)} {traceback.format_exc()}")


def run_job(name):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)
    if not job:
        print(f"No job found with the name {name}")
        return False

    url = job["url"]
    latest_file = download_url(url, name)
    try:
        return process_downloaded_job(job, latest_file)
    except BaseException:
        if os.path.exists(latest_file):
            os.remove(latest_file)
        raise


def process_downloaded_job(job, latest_file):
    name = job["name"]
    url = job["url"]
    metadata = load_metadata()
    snapshots = get_snapshot_versions(name)
    previous_versions = [path for _, path in snapshots if path != latest_file]
    last_emailed_version = metadata.get(name, {}).get("last_emailed_version")

    if last_emailed_version is None and not previous_versions:
        with open(latest_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        context_text = extract_text_from_html(html_content)
        log_message(f"First-time check for job {name} at {url}")
        if context_text == '':
            log_message(f"First-time check for job {name} at {url} got no data from the page.")
            return False
        summary, brief_summary = summarize_page(context_text, url, name, job)
        subject, body = create_summary_email_content(job["name"], url, brief_summary, summary)
        send_email(job["name"], subject, body, load_config()['to_email'])
        metadata[name] = {"last_emailed_version": latest_file}
        save_metadata(metadata)
        return True
    if last_emailed_version is None:
        last_emailed_version = previous_versions[0]
        log_message(
            f"No email baseline was recorded for job {name}; "
            f"using oldest available snapshot {os.path.basename(last_emailed_version)}."
        )

    if not os.path.exists(last_emailed_version):
        if not previous_versions:
            log_message(
                f"Last emailed version is missing for job {name}; sending a recovery summary."
            )
            metadata.pop(name, None)
            with open(latest_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
            context_text = extract_text_from_html(html_content)
            if not context_text:
                return False
            summary, brief_summary = summarize_page(context_text, url, name, job)
            subject, body = create_summary_email_content(job["name"], url, brief_summary, summary)
            send_email(job["name"], subject, body, load_config()['to_email'])
            metadata[name] = {"last_emailed_version": latest_file}
            save_metadata(metadata)
            return True
        last_emailed_version = previous_versions[0]
        log_message(
            f"Last emailed version is missing for job {name}; "
            f"using oldest available snapshot {os.path.basename(last_emailed_version)}."
        )

    diff_text, all_text = compare_files(last_emailed_version, latest_file)
    if not diff_text:
        log_message(f"No changes detected for job: {name}")
        return False

    print(f"DIFF TEXT: {len(diff_text)} characters")
    with open(latest_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    log_message(f"Detected changes for job {name} at {url}")

    summary, score, brief_summary = summarize_diff(
        diff_text, all_text, html_content, url, name
    )
    if score < MIN_SCORE:
        log_message(f"Score {score} below threshold for job {name}. Email not sent.")
        return False

    subject, body = create_email_content(
        job["name"], url, brief_summary, summary, diff_text, score,
        latest_file, [last_emailed_version, latest_file]
    )
    send_email(job["name"], subject, body, load_config()['to_email'])
    metadata[name] = {"last_emailed_version": latest_file}
    save_metadata(metadata)
    return True

def add_job(name, url, frequency):
    jobs = parse_cron_file()
    url = normalize_url(url)

    if any(job['url']==url for job in jobs):
        print("a job with this URL already exists.")
        return

    if name:
        if not is_valid_job_name(name):
            print("Error: Job name must contain only letters, numbers, hyphens, or underscores.")
            return
        if any(job['name'] == name for job in jobs):
            print(f"Error: A job with the name '{name}' already exists.")
            return
    else:
        try:
            name = get_gpt_name(url)
        except ValueError as e:
            print(f"Error: {str(e)}")
            print("Job addition failed. Please provide a valid, unique name manually.")
            return



    if not is_valid_url(url):
        print("Error: Invalid URL format.")
        return

    if frequency not in VALID_FREQUENCIES:
        print(f"Error: Invalid frequency, must be one of {', '.join(VALID_FREQUENCIES)}")
        return

    backup_cron_file()
    jobs.append({
        "frequency": frequency,
        "name": name,
        "url": url,
        "date_added": datetime.now().strftime('%Y%m%d%H%M%S')
    })
    write_cron_jobs(jobs)
    print(f"Job '{name}' added successfully.")
    log_message(f"Job added: {name}, {url}, {frequency}")


def remove_job(name):
    jobs = parse_cron_file()
    if not any(job["name"] == name for job in jobs):
        print(f"No job found with the name {name}")
        return
    backup_cron_file()
    remaining_jobs = [job for job in jobs if job["name"] != name]
    write_cron_jobs(remaining_jobs)
    log_message(f"Job removed: {name}")

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

    write_cron_jobs(jobs)

    print(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}' successfully.")
    log_message(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}'")

def list_jobs(sort_by=None):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    # Modify date_added fields for display and timeline creation
    for job in jobs:
        if job['date_added'] == '00000000000000':
            job['display_date'] = datetime(2024, 6, 1)
        else:
            job['display_date'] = datetime.strptime(job['date_added'], '%Y%m%d%H%M%S')

    if sort_by == "date":
        jobs.sort(key=lambda x: x["display_date"])
    elif sort_by == "url":
        jobs.sort(key=lambda x: x["url"].split('//')[-1])
    elif sort_by == "name":
        jobs.sort(key=lambda x: x["name"].lower())

    max_lengths = [max(len(str(job[key])) for job in jobs) for key in ["frequency", "name", "url"]]
    max_lengths.append(max(len(job['display_date'].strftime('%Y-%m-%d %H:%M:%S')) for job in jobs))

    print("Current monitoring jobs:")
    print(f"{'Frequency'.ljust(max_lengths[0])}  {'Name'.ljust(max_lengths[1])}  {'URL'.ljust(max_lengths[2])}  {'Date Added'.ljust(max_lengths[3])}")
    print("=" * (sum(max_lengths) + 6))
    for job in jobs:
        date_added = job['display_date'].strftime('%Y-%m-%d %H:%M:%S')
        print(f"{job['frequency'].ljust(max_lengths[0])}  {job['name'].ljust(max_lengths[1])}  {job['url'].ljust(max_lengths[2])}  {date_added}")

    # Summary statistics
    total_pages = len(jobs)
    interval_counts = Counter(job['frequency'] for job in jobs)

    print("\nSummary:")
    print(f"Total pages monitored: {total_pages}")
    print("Pages per update interval:")
    for interval, count in interval_counts.items():
        print(f"  {interval}: {count}")

    # Visual ASCII graph of add times grouped by week
    print("\nJob addition timeline (grouped by week):")
    timeline = create_weekly_timeline(jobs)
    print(timeline)

def create_weekly_timeline(jobs):
    earliest = min(job['display_date'] for job in jobs)
    latest = max(job['display_date'] for job in jobs)

    # Adjust earliest to the start of its week (Monday)
    earliest -= timedelta(days=earliest.weekday())

    # Calculate the number of weeks
    weeks = (latest - earliest).days // 7 + 1

    timeline = [' ' * 50 for _ in range(10)]
    weekly_counts = Counter()

    for job in jobs:
        week_number = (job['display_date'] - earliest).days // 7
        weekly_counts[week_number] += 1

    max_count = max(weekly_counts.values()) if weekly_counts else 1
    for week, count in weekly_counts.items():
        height = int((count / max_count) * 9)
        for i in range(height):
            pos = int((week / weeks) * 49)
            timeline[9-i] = timeline[9-i][:pos] + '|' + timeline[9-i][pos+1:]

    timeline.insert(0, earliest.strftime('%Y-%m-%d') + ' ' * 40 + latest.strftime('%Y-%m-%d'))
    timeline.append('-' * 50)

    # Add the new row indicating weeks in the past
    weeks_ago = [' ' * 50]
    for i in range(weeks):
        pos = int((i / weeks) * 49)
        weeks_back = weeks - i - 1
        if i == weeks - 1:
            label = "today"
        else:
            label = f"-{weeks_back}"
        weeks_ago[0] = weeks_ago[0][:pos] + label.ljust(4) + weeks_ago[0][pos+4:]

    timeline.append(weeks_ago[0])

    return '\n'.join(timeline)

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
    write_cron_jobs(jobs)

    print(f"Jobs sorted by {sort_by} and saved back to .gptcron")
    log_message(f"Jobs sorted by {sort_by} and saved back to .gptcron")


def parse_frequency(frequency):
    return {'hourly': 3600, 'daily': 86400, 'weekly': 604800, 'minutely': 60, 'monthly': 2592000}[frequency]

def is_permanent_http_error(status_code):
    if status_code == 429:
        return False
    return 400 <= status_code < 600


def check_cron(force=False):
    lock_file = open(CRON_LOCK_FILE, 'w')
    lock_acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_acquired = True
        except BlockingIOError:
            log_message("Another check_cron process is already running; skipping this run.")
            return
        run_cron_checks(force=bool(force))
    finally:
        try:
            if lock_acquired:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def run_cron_checks(force=False):
    now = time.time()
    jobs = parse_cron_file()
    total_jobs = len(jobs)
    jobs_with_changes = 0
    emails_sent = 0
    emails_failed = 0
    accumulated_errors = []

    for job in jobs:
        frequency = job['frequency']
        name = job['name']
        url = job['url']
        try:
            _, last_run_time = get_last_file(name)
            if last_run_time is None:
                last_run_time = 0
            next_run_time = last_run_time + parse_frequency(frequency)
            if now < next_run_time and not force:
                continue

            log_message(f"Running job: {name}")
            changes_detected = run_job(name)
            if changes_detected:
                jobs_with_changes += 1
                emails_sent += 1
                log_message(f"Changes were detected and emailed for job: {name}")
            else:
                log_message(f"No significant changes detected for job: {name}")
        except EmailDeliveryError as e:
            emails_failed += 1
            log_message(f"Email delivery failed for job {name}: {str(e)}")
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if is_permanent_http_error(status_code):
                error_type = "Page Not Found" if status_code == 404 else f"HTTP {status_code}"
                accumulated_errors.append({
                    'job_name': name,
                    'url': url,
                    'status_code': status_code,
                    'error_type': error_type
                })
                log_message(f"Permanent HTTP error for job {name}: {status_code} - {url}")
            else:
                log_message(f"Temporary HTTP error for job {name}: {status_code} - will retry next run")
        except requests.exceptions.RequestException as e:
            log_message(f"Network error for job {name}: {str(e)} - will retry next run")
        except Exception as e:
            log_message(f"Unexpected error for job {name}: {str(e)}")
            log_message(traceback.format_exc())

    log_message(f"Checked cron jobs. Total: {total_jobs}, Changes: {jobs_with_changes}, Emails Sent: {emails_sent}, Emails Failed: {emails_failed}")

    if accumulated_errors:
        log_message(f"Sending batch error notification for {len(accumulated_errors)} permanent error(s)")
        try:
            send_batch_error_email(accumulated_errors)
        except EmailDeliveryError as e:
            log_message(f"Failed to send batch error notification: {str(e)}")


def search_jobs(query):
    jobs = parse_cron_file()
    matching_jobs = [job for job in jobs if query.lower() in job["name"].lower() or query.lower() in job["url"].lower()]

    if not matching_jobs:
        print(f"No jobs found matching '{query}'.")
        return

    max_lengths = [max(len(str(job[key])) for job in matching_jobs) for key in ["frequency", "name", "url", "date_added"]]

    print(f"Jobs matching '{query}':")
    print(f"{'Frequency'.ljust(max_lengths[0])}  {'Name'.ljust(max_lengths[1])}  {'URL'.ljust(max_lengths[2])}  {'Date Added'.ljust(max_lengths[3])}")
    print("=" * (sum(max_lengths) + 6))
    for job in matching_jobs:
        print(f"{job['frequency'].ljust(max_lengths[0])}  {job['name'].ljust(max_lengths[1])}  {job['url'].ljust(max_lengths[2])}  {job['date_added'].ljust(max_lengths[3])}")


def get_last_n_versions(name, n=5):
    snapshots = get_snapshot_versions(name)
    return [path for _, path in reversed(snapshots[-n:])]

def preprocess_json(s):
    output = []
    in_string = False
    escaped = False
    for character in s:
        if escaped:
            output.append(character)
            escaped = False
        elif character == '\\' and in_string:
            output.append(character)
            escaped = True
        elif character == '"':
            output.append(character)
            in_string = not in_string
        elif character in '\r\n':
            output.append('\\n' if in_string else ' ')
        else:
            output.append(character)
    return ''.join(output)

def attempt_to_deserialize_openai_json(response_text):
    if not isinstance(response_text, str):
        return "", False

    stripped_text = response_text.strip()
    fenced_match = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', stripped_text, re.DOTALL | re.IGNORECASE)
    candidates = [stripped_text]
    if fenced_match:
        candidates.insert(0, fenced_match.group(1).strip())
    candidates.extend(html.unescape(candidate) for candidate in list(candidates))

    for candidate in candidates:
        try:
            return json.loads(preprocess_json(candidate)), True
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    print(f"Bad deserialization of json: {response_text}")
    return "", False

def adjust_job_frequency(name, direction):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)
    if not job:
        print(f"No job found with the name {name}")
        return

    current_index = VALID_FREQUENCIES.index(job["frequency"])
    if direction == "bump":
        if current_index == 0:
            print(f"Job '{name}' is already at the highest frequency ({job['frequency']}).")
            return
        new_index = current_index - 1
    else:  # unbump
        if current_index == len(VALID_FREQUENCIES) - 1:
            print(f"Job '{name}' is already at the lowest frequency ({job['frequency']}).")
            return
        new_index = current_index + 1

    new_frequency = VALID_FREQUENCIES[new_index]
    job["frequency"] = new_frequency
    backup_cron_file()

    write_cron_jobs(jobs)

    action = "bumped" if direction == "bump" else "unbumped"
    print(f"Job '{name}' frequency {action} from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}' successfully.")
    log_message(f"Job '{name}' frequency {action} from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}'")

def send_error_email(error_message):
    config = load_config()
    subject = "Gpt-diff Error Notification"
    body = f"""
    <html>
    <body>
    <h2>An error occurred in the gpt-diff program:</h2>
    <pre>{html.escape(error_message)}</pre>
    <p>Please check the logs for more details.</p>
    </body>
    </html>
    """
    inner_send_email(subject, body, config['to_email'])
    log_message(f"Error email sent: {error_message}")

def send_batch_error_email(errors):
    if not errors:
        return

    config = load_config()
    error_count = len(errors)
    subject = f"Gpt-diff: {error_count} job(s) with permanent errors"

    error_rows = ""
    for err in errors:
        error_rows += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>{html.escape(err['job_name'])}</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;"><a href="{html.escape(err['url'])}">{html.escape(err['url'])}</a></td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #c0392b;">{err['status_code']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{html.escape(err['error_type'])}</td>
        </tr>"""

    body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #c0392b; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 15px; }}
            th {{ background-color: #34495e; color: white; padding: 10px; text-align: left; }}
            .note {{ background-color: #ffeaa7; padding: 10px; border-radius: 5px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <h2>⚠️ Permanent Errors Detected in {error_count} Job(s)</h2>
        <p>The following jobs encountered permanent HTTP errors (site gone, page deleted, etc.) during this cron run:</p>

        <table>
            <tr>
                <th>Job Name</th>
                <th>URL</th>
                <th>Status</th>
                <th>Error Type</th>
            </tr>
            {error_rows}
        </table>

        <div class="note">
            <strong>Note:</strong> These jobs will continue to fail until the URLs are corrected or the jobs are removed.
            Consider running <code>python gptcron.py remove &lt;job_name&gt;</code> for defunct pages.
        </div>

        <p style="color: #7f8c8d; margin-top: 20px;">
            Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>
    </body>
    </html>
    """

    inner_send_email(subject, body, config['to_email'])
    log_message(f"Batch error email sent for {error_count} job(s): {', '.join(e['job_name'] for e in errors)}")

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
                if name in VALID_FREQUENCIES:
                    frequency=name
                    name=""
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
            elif args.command == "search":
                search_jobs(args.query)
            elif args.command == "bump":
                adjust_job_frequency(args.name, "bump")
            elif args.command == "unbump":
                adjust_job_frequency(args.name, "unbump")
            elif args.command == "test":
                test_job(args.name)
            elif args.command == "compare_wikis":
                compare_wikis(args.subject, args.send_email)
            else:
                parser.print_help()
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        log_message(error_message)
        try:
            send_error_email(error_message)
        except Exception as email_error:
            log_message(f"Could not send error notification: {str(email_error)}")
        raise
