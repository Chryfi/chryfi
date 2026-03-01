#!/usr/bin/env python3
"""Fetch GitHub statistics for Chryfi and update README.md markers."""

import os
import re
import time
import requests
from datetime import datetime, timezone
import json

TOKEN = os.environ.get('GH_PAT')
USERNAME = 'Chryfi'
START_YEAR = 2018

now = datetime.now(timezone.utc)
CURRENT_YEAR = now.year

REST_HEADERS = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github.v3+json',
}
GQL_HEADERS = {
    'Authorization': f'bearer {TOKEN}',
    'Content-Type': 'application/json',
}
GQL_URL = 'https://api.github.com/graphql'

CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestReviewContributions
      totalPullRequestContributions
    }
  }
}
"""


def gql(query, variables=None):
    r = requests.post(GQL_URL, json={'query': query, 'variables': variables or {}}, headers=GQL_HEADERS)
    r.raise_for_status()
    data = r.json()
    if 'errors' in data:
        raise RuntimeError(data['errors'])
    return data['data']


# Accumulate contributions year by year via GitHub GraphQL
total_commits = total_reviews = total_prs = 0
year_commits = year_reviews = year_prs = 0

for year in range(START_YEAR, CURRENT_YEAR + 1):
    from_dt = f'{year}-01-01T00:00:00Z'
    to_dt = (now.strftime('%Y-%m-%dT%H:%M:%SZ') if year == CURRENT_YEAR
             else f'{year}-12-31T23:59:59Z')
    data = gql(CONTRIB_QUERY, {'login': USERNAME, 'from': from_dt, 'to': to_dt})
    cc = data['user']['contributionsCollection']
    total_commits += cc['totalCommitContributions']
    total_reviews += cc['totalPullRequestReviewContributions']
    total_prs += cc['totalPullRequestContributions']
    if year == CURRENT_YEAR:
        year_commits = cc['totalCommitContributions']
        year_reviews = cc['totalPullRequestReviewContributions']
        year_prs = cc['totalPullRequestContributions']


def fetch_repos() -> [dict]:
    """Return all repos with any affiliation by USERNAME."""
    print("Start fetching all repositories")
    repos = []
    page = 1
    while True:
        r = requests.get(
            'https://api.github.com/user/repos',
            params={'per_page': 100, 'page': page, 'affiliation': 'owner,collaborator,organization_member'},
            headers=REST_HEADERS,
        )
        r.raise_for_status()
        batch = r.json()
        print(f"{page} 100 page REST Return: ")
        print("".join(batch[i]["name"] + ", " for i in range(len(batch))))
        if not batch:
            break
        repos.extend(repo for repo in batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_stats(owner, repo_name) -> dict:
    """Return (all_time_net_loc, current_year_net_loc) for USERNAME in repo."""
    url = f'https://api.github.com/repos/{owner}/{repo_name}/stats/contributors'
    year_start_ts = int(datetime(CURRENT_YEAR, 1, 1, tzinfo=timezone.utc).timestamp())
    year_end_ts = int(datetime(CURRENT_YEAR + 1, 1, 1, tzinfo=timezone.utc).timestamp())

    print(f"Fetching contributor stats in repo {repo_name} for owner {owner}")
    stats = {
        "loc_added_total": 0,
        "loc_removed_total": 0,
        "loc_added_current_year": 0,
        "loc_removed_current_year": 0
    }
    username_lower = USERNAME.lower()
    # try 8 attempts with a safety delay if error happens
    for attempt in range(8):
        r = requests.get(url, headers=REST_HEADERS)
        if r.status_code == 200:
            contributors = r.json() or []
            
            for c in contributors:
                if not isinstance(c, dict):
                    continue
                author = c.get('author', {})
                if author is None or author.get('login', '').lower() != username_lower:
                    continue
                weeks = c.get('weeks', [])
                for w in weeks:
                    stats["loc_added_total"] += w['a']
                    stats["loc_removed_total"] += w['d']
                    if year_start_ts <= w['w'] < year_end_ts:
                        stats["loc_added_current_year"] += w['a']
                        stats["loc_removed_current_year"] += w['d']

                print(f"Found contributor {author["login"]} in {repo_name}\n")
                return stats
            return stats
        elif r.status_code == 202:
            delay = 5 * (attempt + 1)
            print(f"Received 202 response, sleeping for {delay}s")
            time.sleep(delay)
        else:
            print(f"Unexpected response code {r.status_code}")
            return stats
    print("Timed out")
    return stats

def fmt(n):
    return f'{n:,}'


def update_marker(text, key, value):
    return re.sub(
        rf'<!-- {key}_START -->.*?<!-- {key}_END -->',
        f'<!-- {key}_START -->{value}<!-- {key}_END -->',
        text,
    )







repos = fetch_repos()
total_stats = {
        "loc_added_total": 0,
        "loc_removed_total": 0,
        "loc_added_current_year": 0,
        "loc_removed_current_year": 0
    }
for repo in repos:
    if repo["name"] == "RHAIPowerBI":
        continue
    stats = fetch_stats(repo['owner']['login'], repo['name'])
    for key in stats:
        total_stats[key] += stats[key]
    # maybe safety delay here helps too many time outs
    time.sleep(1)

with open('README.md') as f:
    content = f.read()

for key, value in [
    ('TOTAL_COMMITS',       fmt(total_commits)),
    ('TOTAL_PRS',           fmt(total_prs)),
    ('TOTAL_REVIEWS',       fmt(total_reviews)),
    ('TOTAL_ADDED_LOC',     fmt(total_stats["loc_added_total"])),
    ('TOTAL_REMOVED_LOC',   fmt(total_stats["loc_removed_total"])),
    ('YEAR_COMMITS',        fmt(year_commits)),
    ('YEAR_PRS',            fmt(year_prs)),
    ('YEAR_REVIEWS',        fmt(year_reviews)),
    ('YEAR_ADDED_LOC',      fmt(total_stats["loc_added_current_year"])),
    ('YEAR_REMOVED_LOC',    fmt(total_stats["loc_removed_current_year"])),
    ('CURRENT_YEAR',  str(CURRENT_YEAR)),
]:
    content = update_marker(content, key, value)

with open('README.md', 'w') as f:
    f.write(content)
