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

FLAG_ONLY_REACT_TO_REPO_TEAM = "repo-team"
FLAG_ONLY_REACT_TO_REPO_ORG = "repo-org"
FLAG_ONLY_REACT_TO_ALL = "all"


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


def _get_default_asana_headers() -> Dict:
    token = environ.get("ASANA_PAT")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    return headers


def _get_default_github_headers() -> Dict:
    token = environ.get("REPO_TOKEN")

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
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
    # (GFM), but because we're also going to have to sanitise the HTML heavily
    # to suit Asana's allowlist of elements (see link in docstring), there's
    # little to be gained from trying to render GFM.
    #
    # Note, too that we strip tags, rather than escape them, because it'd create
    # a mess in Asana. We do add a note if the body has changed - but ignoring
    # insignificant changes to the issue_body takes a little legwork:

    content_changed_during_sanitization = False
    content_disclaimer_string = ""

    rendered_issue_body = markdown(issue_body)

    # Do a first pass of sanitisation that includes a <p>, which we'll later drop
    # We do this because it's simpler than covering the various cases where a
    # new line is added/not added.
    ASANA_ALLOWED_TAGS_FOR_TASKS__PLUS_P = ASANA_ALLOWED_TAGS_FOR_TASKS.union("p")

    sanitised_issue_body = bleach.clean(
        rendered_issue_body,
        tags=ASANA_ALLOWED_TAGS_FOR_TASKS__PLUS_P,
        strip=True,
    )

    # Is the sanitised body (so far) the same as the HTML rendered from markdown?
    # (aside from a <hr /> tweaked for HTML5)
    rendered_issue_body_adjusted_for_insignificant_changes = rendered_issue_body.replace("<hr />", "<hr>")

    if sanitised_issue_body != rendered_issue_body_adjusted_for_insignificant_changes:
        content_changed_during_sanitization = True
        content_disclaimer_string = "<hr>\nNote: The original Issue contained content which cannot be displayed in an Asana Task"

    # OK, now drop the <p> tags:
    sanitised_issue_body = bleach.clean(
        sanitised_issue_body,
        tags=ASANA_ALLOWED_TAGS_FOR_TASKS,
        strip=True,
    )

    html_body = dedent(
        f"""\
        <body>
        <i>Issue created <a href="{issue_url}">in Github</a> at {formatted_timestamp}</i>
        <hr>
        <strong>Description</strong> from <a href="{issue_url}">Github</a>:
        {sanitised_issue_body}
        {content_disclaimer_string}
        </body>"""
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
        headers=_get_default_asana_headers(),
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

    REPO_TOKEN = environ.get("REPO_TOKEN")

    if not REPO_TOKEN:
        log("No REPO_TOKEN found - cannot update Issue")
        return

    commenting_url = f"{issue_api_url}/comments"  # NB: no trailing slashj
    headers = _get_default_github_headers()
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


def _may_bridge_to_asana(actor: str, repo_info: str) -> bool:
    """If this is used on a public repo, we don't want to sync every issue
    to Asana. So, for now we'll only sync issues opened by people who are
    members of teams with access to the repository.

    Args:
        actor (string):     The username of whoever opened the isue
        repo_info (string): The name of the org and repo - e.g. octocat/Hello-World

    Returns:
        bool: Whether the actor is a member of a team associated with the repo
    """

    only_react_to_flag = environ.get("ONLY_REACT_TO")

    headers = _get_default_github_headers()
    if only_react_to_flag == FLAG_ONLY_REACT_TO_ALL:
        # Nothing to check - just forward everyone's issues -- this is probably
        # only wise on a private repo.
        log("All Issues are being bridged to Asana.")
        return

    elif only_react_to_flag == FLAG_ONLY_REACT_TO_REPO_TEAM:
        # If the actor is in a team that's associated with the repo, we'll allow it
        repo_teams_url = f"https://api.github.com/repos/{repo_info}/teams"

        raw_teams_resp = requests.get(repo_teams_url, headers=headers)
        if raw_teams_resp.status_code != 200:
            log(f"Problem getting teams data for {repo_info}: {raw_teams_resp} {raw_teams_resp.content}")
            sys.exit(1)

        teams = json.loads(raw_teams_resp.text)
        _templated_member_urls_for_repo = [x["members_url"] for x in teams if x.get("members_url")]
        # Trim out the templated member name from the URLs:
        member_urls_for_repo = [x.replace("{/member}", "") for x in _templated_member_urls_for_repo]

        for members_url in member_urls_for_repo:
            raw_members_resp = requests.get(members_url, headers=headers)
            if raw_members_resp.status_code != 200:
                log(f"Problem getting members data for a team of {repo_info}: {raw_members_resp} {raw_members_resp.content}")
                sys.exit(1)

            members = [x["login"] for x in json.loads(raw_members_resp.text)]
            if actor in members:
                log("Issue actor is on a team associated with the repo.")
                return True

    elif only_react_to_flag == FLAG_ONLY_REACT_TO_REPO_ORG:
        # If the actor is in the same org as the repo is, we'll allow it
        org_name = repo_info.split("/")[0]
        repo_parent_org_members_url = f"https://api.github.com/orgs/{org_name}/members"
        raw_org_members_resp = requests.get(repo_parent_org_members_url, headers=headers)
        if raw_org_members_resp.status_code != 200:
            log(f"Problem getting member data for {org_name}: {raw_org_members_resp} {raw_org_members_resp.content}")
            sys.exit(1)

        members = [x["login"] for x in json.loads(raw_org_members_resp.text)]
        if actor in members:
            log(f"Issue actor {actor} is part of the {org_name} org that owns this repo.")
            return True

    log("Bridging this issue to Asana is not allowed")
    return False


def main() -> None:
    """Initially, just create a new Asana Task based on the GH Issue
    related to triggering this action

    TODO:
    * Updating Asana tasks when issues are updated
    * Closing tasks when issues are closed
    """

    github_repo = environ.get("REPO")
    actor = environ.get("ACTOR")

    if not _may_bridge_to_asana(actor=actor, repo_info=github_repo):
        log(f"{actor} is not in a team associated with {github_repo}. Not mirroring Issue to Asana")
        return

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
