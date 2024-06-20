#!/usr/bin/env python3

import os
import re
import sys
import argparse
import time
from email_utils import send_email, save_email_to_disk, create_email_content, email_me_gptcron
from file_utils import parse_cron_file, backup_cron_file, get_last_file, compare_files, download_url, is_valid_url
from job_utils import add_job, remove_job, change_frequency, list_jobs, save_sorted_jobs, run_job, parse_frequency, check_cron
from openai_utils import summarize_diff
from misc_utils import load_config, load_apikey, log_message, load_metadata, save_metadata, debug_json_parsing

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
print('changing to:', script_dir)
os.chdir(script_dir)

VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']

def setup_argparse():
    parser = argparse.ArgumentParser(description='GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: `add <URL> [weekly|daily|hourly|minutely]` or `add <URL> <name> [weekly|daily|hourly|minutely]`')
    add_parser.add_argument('name', type=str, nargs='?', help='Alphanumeric label for this job')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('frequency', type=str, nargs='?', choices=VALID_FREQUENCIES, help='Frequency to check the URL (e.g weekly|daily|hourly|minutely)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    email_me_gptcron = subparsers.add_parser('email-backup', help='Email me the backup of .gptcron for safekeeping. Usage: email-backup.')

    subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs.')

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


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ["help", "-h", "--h"]:
            print_help()
        else:
            parser = setup_argparse()
            args = parser.parse_args()
            log_message(f"Command called: {args.command}")

            if args.command == "add":
                add_job(args.name, args.url, args.frequency)
            elif args.command == "run":
                run_job(args.name)
            elif args.command == "check_cron":
                check_cron()
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
