#!/usr/bin/env python3
"""Fetch GitHub statistics for Chryfi and update README.md markers."""

import os
import re
import time
import requests
from datetime import datetime, timezone

TOKEN = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
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


def get_repos():
    """Return all repos with any affiliation by USERNAME."""
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
        if not batch:
            break
        repos.extend(repo for repo in batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def get_loc(owner, repo_name):
    """Return (all_time_net_loc, current_year_net_loc) for USERNAME in repo."""
    url = f'https://api.github.com/repos/{owner}/{repo_name}/stats/contributors'
    year_start_ts = int(datetime(CURRENT_YEAR, 1, 1, tzinfo=timezone.utc).timestamp())
    year_end_ts = int(datetime(CURRENT_YEAR + 1, 1, 1, tzinfo=timezone.utc).timestamp())

    username_lower = USERNAME.lower()
    for attempt in range(6):
        r = requests.get(url, headers=REST_HEADERS)
        if r.status_code == 200:
            contributors = r.json() or []
            for c in contributors:
                if not isinstance(c, dict):
                    continue
                if c.get('author', {}).get('login', '').lower() != username_lower:
                    continue
                weeks = c.get('weeks', [])
                all_loc = sum(w['a'] - w['d'] for w in weeks)
                year_loc = sum(
                    w['a'] - w['d'] for w in weeks
                    if year_start_ts <= w['w'] < year_end_ts
                )
                return all_loc, year_loc
            return 0, 0
        elif r.status_code == 202:
            time.sleep(5 * (attempt + 1))
        else:
            return 0, 0
    return 0, 0


repos = get_repos()
total_loc = 0
year_loc = 0
for repo in repos:
    repo_total, repo_year = get_loc(repo['owner']['login'], repo['name'])
    total_loc += repo_total
    year_loc += repo_year


def fmt(n):
    return f'{n:,}'


def update_marker(text, key, value):
    return re.sub(
        rf'<!-- {key}_START -->.*?<!-- {key}_END -->',
        f'<!-- {key}_START -->{value}<!-- {key}_END -->',
        text,
    )


with open('README.md') as f:
    content = f.read()

for key, value in [
    ('TOTAL_COMMITS', fmt(total_commits)),
    ('TOTAL_PRS',     fmt(total_prs)),
    ('TOTAL_REVIEWS', fmt(total_reviews)),
    ('TOTAL_LOC',     fmt(total_loc)),
    ('YEAR_COMMITS',  fmt(year_commits)),
    ('YEAR_PRS',      fmt(year_prs)),
    ('YEAR_REVIEWS',  fmt(year_reviews)),
    ('YEAR_LOC',      fmt(year_loc)),
    ('CURRENT_YEAR',  str(CURRENT_YEAR)),
]:
    content = update_marker(content, key, value)

with open('README.md', 'w') as f:
    f.write(content)

print(f'All-time: commits={total_commits}, PRs={total_prs}, reviews={total_reviews}, LOC={total_loc}')
print(f'{CURRENT_YEAR}: commits={year_commits}, PRs={year_prs}, reviews={year_reviews}, LOC={year_loc}')
