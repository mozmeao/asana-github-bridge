#! /usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import sys
from os import environ
from textwrap import dedent
from typing import Dict, Tuple

import bleach
import requests
from markdown import markdown

ASANA_API_ROOT = "https://app.asana.com/api/1.0/"
ASANA_TASK_COLLECTION_ENDPOINT = f"{ASANA_API_ROOT}tasks"
ASANA_PROJECT = environ.get("ASANA_PROJECT")


# https://developers.asana.com/docs/rich-text#reading-rich-text
ASANA_ALLOWED_TAGS_FOR_TASKS = {
    "a",
    "body",
    "code",
    "em",
    "h1",
    "h2",
    "hr",
    "li",
    "ol",
    "s",
    "strong",
    "u",
    "ul",
}


def log(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.write("\n")


def _get_default_headers() -> Dict:
    token = environ.get("ASANA_PAT")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    return headers


def _build_task_body(issue_body: str, issue_timestamp: str, issue_url: str) -> Tuple[str, bool]:
    """Build a HTML string we can use for the task body in Asana.

    Note that only certain HTML tags are allowed, else the task creation
    will fail. See https://developers.asana.com/docs/rich-text#reading-rich-text

    Also note that line breaks (\n) are preserved and each line is rendered as a <p>

    Returns:
        str: the formatted HTML for Asana
        bool: whether the issue_body passed in has changed during re-formatting
    """

    datestamp, timestamp = issue_timestamp.split("T")
    timestamp = timestamp.replace("Z", " UTC")
    formatted_timestamp = f"{datestamp} {timestamp}"

    # The issue_body is formatted with Markdown, which we need to render
    # to HTML for Asana to display. Strictly, it's Github-Flavored Markdown
    # (GFM), but because we're later going to have to sanitise the HTML heavily
    # to suit Asana's allowlist of elements (see link in docstring), there's
    # little to be gained from trying to render GFM.
    #
    # Note, too that we strip tags, rather than escape them, because it'd create
    # a mess in Asana. We do add a note if the body has changed
    content_changed_during_sanitization = False
    content_disclaimer_string = ""

    rendered_issue_body = markdown(issue_body)

    sanitised_issue_body = bleach.clean(
        rendered_issue_body,
        tags=ASANA_ALLOWED_TAGS_FOR_TASKS,
        strip=True,
    )
    if sanitised_issue_body != rendered_issue_body:
        content_changed_during_sanitization = True

    if content_changed_during_sanitization:
        content_disclaimer_string = "<hr>\nNote: The original Issue contained content which cannot be displayed in an Asana Task"

    html_body = dedent(
        f"""\
        <body>
            <i>Issue created <a href="{issue_url}">in Github</a> at {formatted_timestamp}</i>
            <hr>
            <strong>Description</strong> from <a href="{issue_url}">Github</a>:
            {sanitised_issue_body}
            {content_disclaimer_string}
        </body>"""  # noqa: E501
    )

    return html_body, content_changed_during_sanitization


def create_task(issue_url, issue_title, issue_body, issue_timestamp) -> Tuple[str, bool]:
    """Create a Task in Asana using the GH Issue values provided.

    Returns:
        str: the URL of the new task
        bool: whether or not the GH Issue's description was adjusted to suit
            the Asana HTML allowlist

    """

    task_permalink = "Error creating Asana task"

    task_body, github_description_changed_for_asana = _build_task_body(
        issue_body=issue_body,
        issue_timestamp=issue_timestamp,
        issue_url=issue_url,
    )

    payload = {
        "data": {
            "projects": [ASANA_PROJECT],
            "name": issue_title,
            "html_notes": task_body,
        }
    }

    resp = requests.post(
        ASANA_TASK_COLLECTION_ENDPOINT,
        json=payload,
        headers=_get_default_headers(),
    )
    if resp.status_code != 201:
        log(resp.content)
    else:
        task_permalink = json.loads(resp.text).get("data", {}).get("permalink_url")
        log(f"Asana task created: {task_permalink}")

    return task_permalink, github_description_changed_for_asana


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
    github_description_changed_for_asana: bool,
) -> None:
    """Update the original Github issue with a comment linking back
    to the Asana task that it spawned"""

    GITHUB_TOKEN = environ.get("GITHUB_TOKEN")

    if not GITHUB_TOKEN:
        log("No GITHUB_TOKEN found - cannot update Issue")
        return

    commenting_url = f"{issue_api_url}/comments"  # NB: no trailing slashj

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    comment = f"This issue has been copied to Asana: {task_permalink}"

    if github_description_changed_for_asana:
        comment += " **However**, some of the content was not mirrored due to markup restrictions."
        comment += " Please review the Asana Task."

    resp = requests.post(
        commenting_url,
        json={"body": comment},
        headers=headers,
    )

    if resp.status_code != 201:
        log(f"Commenting failed: {resp.content}")
    else:
        log("Asana task URL added in comment on original issue")


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

    task_permalink, github_description_changed_for_asana = create_task(
        issue_url=issue_url,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_timestamp=issue_timestamp,
    )

    add_task_as_comment_on_github_issue(
        issue_api_url=_transform_to_api_url(issue_url),
        task_permalink=task_permalink,
        github_description_changed_for_asana=github_description_changed_for_asana,
    )


if __name__ == "__main__":
    main()
