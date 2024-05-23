I want to make a command line program for "gpt-diff". It should be like "gpt-diff add <name> <URL> [daily|hourly|weekly] etc.". That would do the following:

1. set up a periodic repeated action to call a wget on that URL and save the results to a file. Then it would compare the current results to the last results, if any, using gpt-4o. So that if the first time, the page said one thing, the 2nd time, the page would say another thing.

If there was a change, that change would trigger an email to me, at my email address. The email would

The program doing the downloading should:
1. be run periodically by a real cron job (which would check all teh gpt-cron jobs I had).
2. download the latest
3. compare to the prior, if any, using a local diff tool
4. if there is any technical bit difference, send the data to gpt4o for summarizing. it should say a general, detailed description.
5. I have an apikey for this so that is fine.
6. once results are back email them to me - both the summarized words of difference, and also the actual diff file produce from the filesystem

I will run this on WSL in windows. The apikey is in a file called apikey.txt

This system also has cron.

So we should also create a general cron that runs say hourly which does all the jobs. Our gptcron jobs will be stored in our own .gptcron file. There will also be a config file which contains my email address.  So when the program runs, it does the work for ech one.

The <name> field must be an alphanumeric label for this job. the data for that job goes in the folder data/<name>. In there, there are lots of files which are named <name-date of last download of the file contents>.  Those are available if needed for deeper comparisons.


Can you give me a general set of intro files for this? It should be written in python

The API at openAI we use must be "gpt-4o" (or later models) even if you haven't head of it yet.

The provided script is a web monitoring tool that tracks changes to specific URLs and sends detailed email summaries of detected changes. It works by periodically downloading the web pages, comparing them with previously downloaded versions, and using OpenAI to generate summaries of the differences. It includes functionalities to add, run, list, and check monitoring jobs, each configured with specific frequencies (hourly, daily, weekly).

We will never use Function Docstrings because they are a waste of space.
