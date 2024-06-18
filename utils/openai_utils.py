import openai
import hashlib
import os
import time
import html
import json
from utils.misc_utils import load_apikey, log_message, extract_text_from_html

def normal(s):
    return json.loads(s)

def magic(s):
    fix = s.strip('```json\n').strip('\n```')
    if fix.startswith('json'):
        fix = fix[4:]
    return json.loads(fix)

def magic2(s):
    s = html.unescape(s)
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def magic3(s):
    s = html.unescape(s)
    s = s.replace('\\\n', '')
    s = s.replace('\\', '')
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def summarize_diff(diff_text, html_content, url, name):
    openai.api_key = load_apikey()
    context_text = extract_text_from_html(html_content)

    loaded_prompt = open('prompt.txt').read().strip()
    combined_text = f"Diff:\n{diff_text}\n{context_text}"[:20000]

    prompt = f"""{loaded_prompt}
        {combined_text}

        Please provide your response in the following JSON format:
        {{
            "summary": "generate a text summary of the webpage. Use newlines to separate paragraphs covering all the main aspects of the page. Make sure to cover it broadly.",
            "brief_summary": "a one-sentence, pure text summary of the changes. This is for use within an email subject line, so it cannot be very long.",
            "score": your_score_here (integer from 1 to 10),
        }}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant which always returns json."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3500
    )

    response_text = response.choices[0].message['content'].strip()
    unique_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(url.encode()).hexdigest()}"

    raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_bad.json"
    got = False
    for attempt in [normal, magic, magic2, magic3]:
        try:
            response_json = attempt(response_text)
            summary = response_json['summary']
            score = int(response_json['score'])
            brief_summary = response_json['brief_summary']
            raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_okay.json"
            got = True
            break
        except (json.JSONDecodeError, KeyError, ValueError):
            log_message(f"Error parsing JSON response: {response_text}")
            os.makedirs('openai_responses', exist_ok=True)
            summary = "Error parsing response"
            brief_summary = "Fail"
            score = 0
    if not got:
        import ipdb
        ipdb.set_trace()
    with open(raw_response_filename, 'w') as f:
        f.write(response_text)
    return summary, score, brief_summary

def summarize_page(context_text, url, name):
    openai.api_key = load_apikey()

    prompt = f"""Please provide a summary of the page content following, using the following JSON format:
        {{
            "summary": "[your_summary_here including all relevant sections, with specific details.]",
            "brief_summary": "a one-sentence, pure text summary of the entire webpage and what it is all about.",
            "score": [your_score_here (integer from 1 to 10) for how globally relevant you think this page is, and how interesting you think it is.],
        }}

        Here is the content to base this JSON upon:

        {context_text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant which always returns json."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3500
    )

    response_text = response.choices[0].message['content'].strip()
    unique_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(url.encode()).hexdigest()}"

    raw_response_filename = f"openai_responses/{name}_{unique_id}_summary.json"
    got = False
    for attempt in [normal, magic, magic2, magic3]:
        try:
            response_json = attempt(response_text)
            summary = response_json['summary']
            brief_summary = response_json['brief_summary']
            raw_response_filename = f"openai_responses/{name}_{unique_id}_summary_okay.json"
            got = True
            break
        except (json.JSONDecodeError, KeyError, ValueError):
            log_message(f"Error parsing JSON response: {response_text}")
            os.makedirs('openai_responses', exist_ok=True)
            summary = "Error parsing response"
    if not got:
        import ipdb
        ipdb.set_trace()
    with open(raw_response_filename, 'w') as f:
        f.write(response_text)
    return summary, brief_summary
