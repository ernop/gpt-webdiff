# Agent Entry Point

Welcome, agent. GPT-WebDiff is a focused tool: watch websites, understand changes, alert humans. You're helping maintain and extend it.

## The Goal: Never Miss What Matters

Users monitor websites that matter to them - news sites, competitor pages, documentation, personal projects. Traditional diff tools show raw changes. GPT-WebDiff uses AI to answer: "What changed, and should I care?"

**Core Value Proposition**: Intelligent, context-aware change summaries delivered via email only when changes are significant.

**Our job**: Transform noise (every HTML change) into signal (meaningful notifications).

---

## How to Do Good Work Here

**Understand before acting.** This is a single-file tool (~1500 lines). Read `gptcron.py` before proposing changes. Small codebase, but each part has purpose.

**Simplicity is sacred.** The single-file design is intentional - easy deployment, no package complexity. Resist the urge to over-engineer.

**Practical over perfect.** Working code beats theoretical elegance. The diff algorithm is acknowledged as imperfect; that's acceptable if it works.

**No docstrings.** Developer preference. Use descriptive function names and inline comments instead.

---

## Documentation Index

### High-Level Concepts

| | |
|-|-|
| How users experience GPT-WebDiff | This file (Product section below) |
| User-facing documentation | `README.md` |
| Setup instructions | `SETUP.md` |
| Usage examples | `USAGE_GUIDE.md` |

### Product Features

| | |
|-|-|
| Website monitoring with AI analysis | Core feature via `add`, `run`, `test` commands |
| Significance scoring (0-10 scale) | Only score >= 7 triggers notification |
| Wikipedia vs Grokipedia comparison | `compare_wikis` command |
| Email notifications | HTML-formatted summaries |
| Job management | `list`, `remove`, `bump`, `unbump`, `search` |

### Technical

| | |
|-|-|
| Main application | `gptcron.py` |
| Configuration | `config.json` (from `config_example.json`) |
| Job definitions | `.gptcron` file |
| Job state tracking | `job_metadata.json` |
| Technical improvement notes | `IMPROVEMENTS.md` |

---

## Product: What Users Experience

### Monitoring Flow

1. User adds a website: `python gptcron.py add "https://news.site" daily`
2. AI generates a short job name (or user specifies one)
3. Cron runs `check_cron` periodically
4. When changes detected, AI analyzes: what changed? how significant?
5. Score >= 7? Email sent with intelligent summary
6. Score < 7? Changes accumulate until next significant batch

### Significance Scoring

The AI rates changes 0-10 based on **context**:

| Score | National News Site | Local Coffee Shop | Company Page |
|-------|-------------------|-------------------|--------------|
| 10 | Invasion, assassination | Going out of business | Major lawsuit, closure |
| 8-9 | Major legislation | Location change | Senior departure |
| 5-7 | Notable incident | Menu changes | Product update |
| 0-4 | Typo fixes, minor updates | Small hours change | Text tweaks |

Only scores >= 7 trigger emails. This prevents notification fatigue.

### Smart Aggregation

If multiple small changes don't reach threshold, they accumulate. Next check compares against the **last emailed version**, not the last downloaded version. This ensures complete coverage.

---

## User Directives

Rules from project owner:

- **No docstrings.** Inline comments and descriptive names instead.
- **No fallbacks for our own failures.** If config is malformed, fail - don't silently use defaults.
- **Keep it simple.** Single file is intentional. Don't split unless there's clear benefit.
- **Backward compatibility.** Existing `.gptcron` files must continue to work.
- **Test manually.** No automated test suite yet. Test both Claude and OpenAI paths.
- **Protect secrets.** Never commit `config.json` or `apikey.txt`.

---

## System Overview

```
[User] --CLI--> [gptcron.py] --HTTP--> [Websites]
                     |
                     +--> [Claude/GPT API] --> Analysis
                     |
                     +--> [Gmail SMTP] --> Email
                     |
                     +--> [Local Storage] --> data/, emails/, openai_responses/
```

**Single-file design**: Everything in `gptcron.py`. Easier to deploy, understand, and distribute.

### Key Systems

| System | Purpose | Location |
|--------|---------|----------|
| CLI | 15+ commands via argparse | `setup_argparse()`, `__main__` |
| LLM | Unified Claude/OpenAI with fallback | `call_llm()` |
| Diff | Text extraction + difflib | `compare_files()` |
| Analysis | AI summarization of changes | `summarize_diff()` |
| Email | Gmail SMTP with HTML templates | `send_email()`, `inner_send_email()` |
| Jobs | `.gptcron` file parsing | `parse_cron_file()` |
| Storage | HTML archives per job | `data/{job_name}/` |

---

## Dev Setup

```bash
# Install
pip install -r requirements.txt

# Configure
cp config_example.json config.json
# Edit config.json: add API keys, email credentials

# Test
python gptcron.py list
python gptcron.py test some-job
```

**Config keys**: `anthropic_api_key`, `openai_api_key`, `to_email`, `login_email`, `password`, `default_model`, `fallback_model`

**Gmail**: Requires [App Password](https://support.google.com/accounts/answer/185833), not regular password.

---

## Coding Rules

**Models**: Default Claude Sonnet 4.5, fallback GPT-4o. Both paths must work.

**JSON parsing**: `attempt_to_deserialize_openai_json()` handles multiple formats - markdown blocks, HTML escaping, etc.

**Adding a command**:
1. Add parser in `setup_argparse()`
2. Add handler function
3. Add case in `__main__` block

**Adding a frequency**: Add to `VALID_FREQUENCIES` list and `parse_frequency()` dict. Done.

**Adding LLM provider**: Import with try/except, update `get_model_config()`, add branch in `call_llm()`.

---

## Terminology

| Term | Meaning |
|------|---------|
| job | A monitored URL with name, frequency, and history |
| frequency | How often to check: minutely, hourly, daily, weekly, monthly |
| score | AI-assigned significance rating 0-10 |
| threshold | Minimum score (7) to trigger email |
| smart aggregation | Compare against last emailed version, not last download |

---

## Tools

```bash
# Job management
python gptcron.py add <url> [name] [frequency]    # Add monitoring job
python gptcron.py list [--sort_by date|url|name]  # List all jobs
python gptcron.py remove <name>                   # Remove job
python gptcron.py search <query>                  # Search jobs
python gptcron.py bump <name>                     # Increase frequency
python gptcron.py unbump <name>                   # Decrease frequency

# Execution
python gptcron.py run <name>                      # Run specific job
python gptcron.py test [name]                     # Test job (random if no name)
python gptcron.py check_cron [force]              # Run all due jobs

# Utilities
python gptcron.py compare_wikis <subject> [--send-email]  # Wiki comparison
python gptcron.py email-backup                    # Backup job list via email
python gptcron.py reparse <name>                  # Debug JSON parsing
```

**Cron setup**: `*/15 * * * * cd /path/to/gpt-webdiff && python3 gptcron.py check_cron >> cronlog.log 2>&1`

---

## Known Issues

| Issue | Status |
|-------|--------|
| Diff algorithm is text-only | Acknowledged; AI compensates |
| JS-rendered content not detected | Would need Selenium/Playwright |
| HTML files accumulate | No auto-cleanup yet |
| Debug code (ipdb) in production | Intentional for rapid debugging |

---

## Storage Structure

```
gpt-webdiff/
├── gptcron.py              # Main application
├── config.json             # Secrets (gitignored)
├── .gptcron                # Job definitions
├── job_metadata.json       # Last emailed versions
├── data/{job-name}/        # Downloaded HTML archives
├── openai_responses/       # AI response logs
├── emails/                 # Sent email copies
├── wiki_comparisons/       # Wiki comparison results
└── gptcron_backups/        # .gptcron file backups
```

---

## Questions

If uncertain, check:
1. The code - it's readable and self-documenting
2. `README.md` for user perspective
3. `IMPROVEMENTS.md` for known tech debt

When in doubt, ask the developer rather than guessing.

---

## Evolving This Document

Add **high-level concepts** here. Keep it tight. Product context helps agents make better decisions than raw technical specs alone.

Max target: ~200 lines. If longer, compress or link to separate docs.
