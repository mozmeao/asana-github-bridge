#! /usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from os import environ
from textwrap import dedent
from typing import Dict

import requests

ASANA_API_ROOT = "https://app.asana.com/api/1.0/"
ASANA_TASK_COLLECTION_ENDPOINT = f"{ASANA_API_ROOT}tasks"
ASANA_PROJECT = environ.get("ASANA_PROJECT")


def _get_default_headers() -> Dict:
    token = environ.get("ASANA_PAT")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    return headers


def _task_body(issue_body: str, issue_timestamp: str, issue_url: str) -> str:
    """Build a HTML string we can use for the task body in Asana.

    Note that only certain HTML tags are allowed, else the task creation
    will fail. See https://developers.asana.com/docs/rich-text#reading-rich-text

    Also note that line breaks (\n) are preserved and each line is rendered as a <p>
    """

    datestamp, timestamp = issue_timestamp.split("T")
    timestamp = timestamp.replace("Z", " UTC")
    formatted_timestamp = f"{datestamp} {timestamp}"

    return dedent(
        f"""\
        <body>
            <strong>Original description</strong> from <a href="{issue_url}">Github</a>:

            {issue_body}
            <hr>
            <i>Issue created <a href="{issue_url}">in Github</a> at {formatted_timestamp}</i>
        </body>"""  # noqa: E501
    )


def create_task(issue_url, issue_title, issue_body, issue_timestamp) -> str:
    "Create a task in Asana and return the URL"

    task_permalink = "Error creating Asana task"

    payload = {
        "data": {
            "projects": [ASANA_PROJECT],
            "name": issue_title,
            "html_notes": _task_body(
                issue_body=issue_body,
                issue_timestamp=issue_timestamp,
                issue_url=issue_url,
            ),
        }
    }

    resp = requests.post(
        ASANA_TASK_COLLECTION_ENDPOINT,
        json=payload,
        headers=_get_default_headers(),
    )
    if resp.status_code != 201:
        print(resp.content)
    else:
        task_permalink = json.loads(resp.text).get("data", {}).get("permalink_url")
        print(f"Asana task created: {task_permalink}")

    return task_permalink


def _transform_to_api_url(html_url: str) -> str:
    """Convert the HTML page URL to an API URL"""

    # Note, we can get this from the GH event, but trading off the number of
    # env vars required to configure the action with a bit of legwork. Risk
    # is if the API URL format changes, of course.

    return html_url.replace(
        "https://github.com/",
        "https://api.github.com/repos/",
        1,  # count of 1
    )


def add_task_as_comment_on_github_issue(
    issue_api_url: str,
    task_permalink: str,
) -> None:
    """Update the original Github issue with a comment linking back
    to the Asana task that it spawned"""

    GITHUB_TOKEN = environ.get("GITHUB_TOKEN")

    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN found - cannot update Issue")
        return

    commenting_url = f"{issue_api_url}/comments"  # NB: no trailing slashj

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "body": f"This issue has been mirrored to Asana: {task_permalink}",
    }

    resp = requests.post(commenting_url, json=payload, headers=headers)

    if resp.status_code != 201:
        print(f"Commenting failed: {resp.content}")
    else:
        print("Asana task URL added in comment on original issue")


def main() -> None:
    """Initially, just create a new Asana Task based on the GH Issue
    related to triggering this action

    TODO:
    * Updating Asana tasks when issues are updated
    * Closing tasks when issues are closed
    """

    issue_url = environ.get("ISSUE_URL")
    issue_title = environ.get("ISSUE_TITLE")
    issue_body = environ.get("ISSUE_BODY")
    issue_timestamp = environ.get("ISSUE_TIMESTAMP")

    task_permalink = create_task(
        issue_url=issue_url,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_timestamp=issue_timestamp,
    )

    add_task_as_comment_on_github_issue(
        issue_api_url=_transform_to_api_url(issue_url),
        task_permalink=task_permalink,
    )


if __name__ == "__main__":
    main()
