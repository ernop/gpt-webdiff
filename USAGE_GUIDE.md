# GPT-WebDiff Usage Guide

## Quick Start for Wiki Comparison Feature

### Setup (if not already done)
```bash
# Install dependencies
pip install -r requirements.txt

# Make sure you have apikey.txt with your OpenAI API key
# Make sure you have config.json configured (for email features)
```

### Compare Wikipedia and Grokipedia Pages

#### Basic Usage
```bash
python gptcron.py compare_wikis "Subject Name"
```

#### Examples
```bash
# Compare pages about Python programming language
python gptcron.py compare_wikis "Python (programming language)"

# Compare pages about climate change
python gptcron.py compare_wikis "Climate change"

# Compare and send results via email
python gptcron.py compare_wikis "Artificial Intelligence" --send-email

# Works with underscores too
python gptcron.py compare_wikis "Machine_learning"
```

### What Happens When You Run It

1. **Fetches Wikipedia Page**
   - Downloads the full Wikipedia article for your subject
   - Example: `https://en.wikipedia.org/wiki/Python_(programming_language)`

2. **Fetches Grokipedia Page**
   - Tries multiple URL patterns to find the Grokipedia article
   - Patterns tried:
     - `https://grokipedia.org/Subject`
     - `https://grok.x.ai/wiki/Subject`
     - `https://x.ai/grokipedia/Subject`

3. **Sends to GPT for Analysis**
   - Sends both full pages to GPT-4o-mini
   - Asks for detailed comparison including:
     - Key differences
     - Missing information
     - Bias assessment
     - Emphasis differences

4. **Outputs Results**
   - **Console Mode** (default): Displays formatted text analysis
   - **Email Mode** (`--send-email`): Sends HTML formatted report via email
   - **File**: Always saves HTML report to `wiki_comparisons/Subject_timestamp.html`

### Understanding the Output

The comparison includes 5 sections:

1. **Detailed Analysis**: Overall comparison and key findings
2. **Wikipedia Unique Points**: Information only in Wikipedia
3. **Grokipedia Unique Points**: Information only in Grokipedia  
4. **Major Differences**: Most significant differences between the two
5. **Bias Assessment**: Analysis of potential biases in either source

### Example Output Structure

```
================================================================================
COMPARISON RESULTS
================================================================================

Subject: Python (programming language)
Wikipedia URL: https://en.wikipedia.org/wiki/Python_(programming_language)
Grokipedia URL: https://grokipedia.org/Python_(programming_language)

--------------------------------------------------------------------------------
DETAILED ANALYSIS:
--------------------------------------------------------------------------------
[GPT's comprehensive analysis of the differences]

--------------------------------------------------------------------------------
WIKIPEDIA UNIQUE POINTS:
--------------------------------------------------------------------------------
[Points only found in Wikipedia]

--------------------------------------------------------------------------------
GROKIPEDIA UNIQUE POINTS:
--------------------------------------------------------------------------------
[Points only found in Grokipedia]

--------------------------------------------------------------------------------
MAJOR DIFFERENCES:
--------------------------------------------------------------------------------
[Most significant differences]

--------------------------------------------------------------------------------
BIAS ASSESSMENT:
--------------------------------------------------------------------------------
[Analysis of any biases detected]

================================================================================
```

### Saved Files

Each comparison creates a file:
```
wiki_comparisons/
  └── Python_(programming_language)_20251107-143022.html
  └── Climate_change_20251107-143155.html
  └── [etc...]
```

These are beautifully formatted HTML files you can open in any browser.

### Troubleshooting

#### "Failed to fetch Wikipedia content"
- Check your internet connection
- Verify the subject name is correct
- Some subjects may have different names on Wikipedia (try variations)

#### "Failed to fetch Grokipedia content from any known URL patterns"
- Grokipedia is very new (launched Oct 2025)
- URL structure may not be what we expect
- You can manually check the Grokipedia site and update the URL patterns in the code
- The relevant code is in the `compare_wikis` function in `gptcron.py`

#### "Error parsing GPT response"
- This is rare but can happen if GPT returns malformed JSON
- Check your API key is valid
- Try again (sometimes transient)
- Check the log file for more details

#### Rate Limiting
- If you make many comparisons quickly, you may hit:
  - OpenAI API rate limits (depends on your plan)
  - Wikipedia/Grokipedia rate limits
- Wait a few minutes between large batches

### Cost Considerations

Each comparison:
- Sends ~50,000 characters of text to GPT-4o-mini
- Costs approximately $0.01-0.02 per comparison
- This varies based on:
  - Length of articles
  - GPT-4o-mini pricing (currently very cheap)
  - Response length

### Tips for Best Results

1. **Use Full Names**: "Python (programming language)" not just "Python"
2. **Check Wikipedia First**: Make sure the article exists on Wikipedia
3. **Controversial Topics**: These will often show the most interesting differences
4. **Historical Figures**: Good for seeing bias differences
5. **Recent Events**: May not be on Grokipedia yet (it's very new)

### Integration with Existing Monitoring

You can combine this with the main monitoring feature:

```bash
# Monitor a page for changes
python gptcron.py add "https://en.wikipedia.org/wiki/Climate_change" "climate-wiki" daily

# Also do a one-time comparison with Grokipedia
python gptcron.py compare_wikis "Climate change"
```

### Advanced Usage

#### Batch Comparisons (via shell script)
```bash
#!/bin/bash
# compare_batch.sh

subjects=(
  "Artificial Intelligence"
  "Climate change"
  "Donald Trump"
  "Joe Biden"
  "Ukraine"
)

for subject in "${subjects[@]}"; do
  echo "Comparing: $subject"
  python gptcron.py compare_wikis "$subject"
  sleep 5  # Avoid rate limits
done
```

#### Email All Results
```bash
python gptcron.py compare_wikis "Python" --send-email
python gptcron.py compare_wikis "Java" --send-email
python gptcron.py compare_wikis "JavaScript" --send-email
```

## Original gpt-webdiff Features

All original features still work exactly as before:

### Monitor Websites
```bash
# Add a site to monitor
python gptcron.py add https://example.com "example" daily

# List all jobs
python gptcron.py list

# Run a specific job manually
python gptcron.py run example

# Check and run all due jobs
python gptcron.py check_cron
```

See the main README.md for full documentation of the original features.

## Questions?

- Check `IMPROVEMENTS.md` for technical details
- Check `README.md` for original feature documentation
- Check the code comments in `gptcron.py`
- The comparison function is `compare_wikis()` starting around line 314

