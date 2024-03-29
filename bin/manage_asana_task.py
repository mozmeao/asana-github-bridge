#! /usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import sys
from os import environ
from textwrap import dedent
from typing import Dict, Iterable, Tuple

import bleach
import requests
from markdown import markdown

ASANA_API_ROOT = "https://app.asana.com/api/1.0/"
ASANA_PROJECT = environ.get("ASANA_PROJECT")
ASANA_TASK_COLLECTION_ENDPOINT = f"{ASANA_API_ROOT}tasks"
ASANA_PROJECT_RESOURCE_ENDPOINT = f"{ASANA_API_ROOT}projects/{ASANA_PROJECT}"

MESSAGE_UNABLE_TO_CREATE_ASANA_PERMALINK = "Error creating Asana task"

FLAG_ONLY_REACT_TO_SPECIFIED_USERS = "specified-users"
FLAG_ONLY_REACT_TO_ALL = "all"


# Asana allows a fairly restrictive set of HTML tags it its Task body.
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


def log(*params: Iterable) -> None:
    sys.stdout.write(" ".join(params))
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


def _get_github_issue_field_gid(field_name: str = "Github Issue") -> str:
    """Discover and return the Asana GID for the custom field we use to link to
    a GH Issue, for the project defined by the ASANA_PROJECT env var.

    The short path is to use an env var, if avaiable.
    The longer path is to query the Asana project and find the field via its name

    Args:
        field_name (str, optional): Name of the custom field to look for. Defaults to "Github Issue".

    Returns:
        str: GID of the Github Issue field in the project.
    """
    issue_field_gid = environ.get("ASANA_GITHUB_ISSUE_CUSTOM_FIELD_GID", "")

    if not issue_field_gid:
        project_resp = requests.get(
            ASANA_PROJECT_RESOURCE_ENDPOINT,
            headers=_get_default_asana_headers(),
        )
        if project_resp.status_code == 200:
            project_data = json.loads(project_resp.text)
            for custom_field_spec in project_data.get("data", {}).get("custom_field_settings", []):
                if custom_field_spec.get("custom_field", {}).get("name").lower() == field_name.lower():
                    issue_field_gid = custom_field_spec.get("custom_field", {}).get("gid")
                    log(f"Custom field {field_name} has gid of {issue_field_gid}")
                    break

    return issue_field_gid


def _build_task_body(
    issue_body: str,
    issue_url: str,
    custom_gh_field_known: bool,
) -> Tuple[str, bool]:
    """Build a HTML string we can use for the task body in Asana.

    Note that only certain HTML tags are allowed, else the task creation
    will fail. See https://developers.asana.com/docs/rich-text#reading-rich-text

    Also note that line breaks (\n) are preserved and each line is rendered as a <p>

    Returns:
        str: the formatted HTML for Asana
        bool: whether the issue_body passed in has changed during re-formatting
    """

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
    optional_link_string = ""

    rendered_issue_body = markdown(issue_body)

    # Do a first pass of sanitisation that includes a <p>, which we'll later drop
    # We do this because it's simpler than comparing the various cases where a
    # new line is added/not added during cleaning (eg before/not before a list)
    ASANA_ALLOWED_TAGS_FOR_TASKS__PLUS_P = ASANA_ALLOWED_TAGS_FOR_TASKS.union("p")

    sanitised_issue_body = bleach.clean(
        rendered_issue_body,
        tags=ASANA_ALLOWED_TAGS_FOR_TASKS__PLUS_P,
        strip=True,
    )

    # Is the sanitised body (so far) the same as the HTML rendered from Markdown?
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

    if not custom_gh_field_known:
        optional_link_string = f'<a href="{issue_url}">Github</a>'

    html_body = dedent(
        f"""\
        <body>
        {sanitised_issue_body}
        {optional_link_string}
        {content_disclaimer_string}
        </body>"""
    )
    return html_body, content_changed_during_sanitization


def create_task(
    issue_url: str,
    issue_title: str,
    issue_body: str,
) -> Tuple[str, bool]:
    """Create a Task in Asana using the GH Issue values provided.

    Returns:
        str: the URL of the new task
        bool: whether or not the GH Issue's description was adjusted to suit
            the Asana HTML allowlist
    """

    task_permalink = MESSAGE_UNABLE_TO_CREATE_ASANA_PERMALINK

    custom_gh_issue_field_gid = _get_github_issue_field_gid()

    custom_fields = {}
    if custom_gh_issue_field_gid:
        custom_fields[custom_gh_issue_field_gid] = issue_url

    task_body, github_description_was_changed_for_asana = _build_task_body(
        issue_body=issue_body,
        issue_url=issue_url,
        custom_gh_field_known=bool(custom_gh_issue_field_gid),
    )

    payload = {
        "data": {
            "projects": [ASANA_PROJECT],
            "name": issue_title,
            "html_notes": task_body,
            "custom_fields": custom_fields,
        }
    }

    resp = requests.post(
        ASANA_TASK_COLLECTION_ENDPOINT,
        json=payload,
        headers=_get_default_asana_headers(),
    )
    if resp.status_code == 201:
        task_permalink = json.loads(resp.text).get("data", {}).get("permalink_url")
        log(f"Asana task created: {task_permalink}")
    else:
        # Something's not right. Log the response and let the caller
        # deal with things when they see task_permalink is a warning message
        log(resp.content)

    return task_permalink, github_description_was_changed_for_asana


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
    github_description_was_changed_for_asana: bool,
) -> None:
    """Update the original Github issue with a comment linking back
    to the Asana task that it spawned"""

    REPO_TOKEN = environ.get("REPO_TOKEN")

    if not REPO_TOKEN:
        log("No REPO_TOKEN found - cannot update Issue")
        return

    commenting_url = f"{issue_api_url}/comments"  # NB: no trailing slash
    headers = _get_default_github_headers()
    comment = f"This issue has been copied to Asana: {task_permalink}"

    if github_description_was_changed_for_asana:
        comment += " **However**, some of the content was not mirrored due to markup restrictions."
        comment += " Please review the Asana Task."

    resp = requests.post(
        commenting_url,
        json={"body": comment},
        headers=headers,
    )

    if resp.status_code != 201:
        log(f"Commenting failed: {resp.text}")
    else:
        log("Asana task URL added in comment on original issue")


def _may_bridge_to_asana(actor: str, repo_info: str) -> bool:
    """If this is used on a public repo, we don't want to sync every issue
    to Asana. So, for now we'll only sync issues opened by people who are
    in allowlist of specific users.

    Args:
        actor (string):     The username of whoever opened the issue
        repo_info (string): The name of the org and repo - e.g. octocat/Hello-World

    Returns:
        bool: Whether the actor is a member of a team associated with the repo
    """

    only_react_to_flag = environ.get("ONLY_REACT_TO")
    actor_allowlist = [x.strip() for x in environ.get("ACTOR_ALLOWLIST", "").split(",")]

    if only_react_to_flag == FLAG_ONLY_REACT_TO_ALL:
        # Nothing to check - just forward everyone's issues -- this is probably
        # only wise on a private repo.
        log("All Issues are being bridged to Asana.")
        return True

    elif only_react_to_flag == FLAG_ONLY_REACT_TO_SPECIFIED_USERS:
        # If the actor is associated with the repo via the allowlist, we'll allow it
        if actor in actor_allowlist:
            log(f"Actor {actor} is in the provided allowlist.")
            return True
        else:
            log(f"Actor {actor} is not in the provided allowlist.")

    log("Bridging this issue to Asana is not allowed")
    return False


def main() -> None:
    """Initially, just create a new Asana Task based on the GH Issue
    related to triggering this action

    TODO (TBC):
    * Updating Asana tasks when issues are updated - or at least commenting in Asana that the GH Issue was updated
    * Closing Tasks when Issues are closed
    """

    github_repo = environ.get("REPO")
    actor = environ.get("ACTOR")

    if not _may_bridge_to_asana(actor=actor, repo_info=github_repo):
        log(f"{actor} is not in the allowlist of users who can trigger mirroring. Not mirroring this Issue to Asana")
        return

    issue_url = environ.get("ISSUE_URL")
    issue_title = environ.get("ISSUE_TITLE")
    issue_body = environ.get("ISSUE_BODY")

    task_permalink, github_description_was_changed_for_asana = create_task(
        issue_url=issue_url,
        issue_title=issue_title,
        issue_body=issue_body,
    )

    if task_permalink != MESSAGE_UNABLE_TO_CREATE_ASANA_PERMALINK:
        add_task_as_comment_on_github_issue(
            issue_api_url=_transform_to_api_url(issue_url),
            task_permalink=task_permalink,
            github_description_was_changed_for_asana=github_description_was_changed_for_asana,
        )


if __name__ == "__main__":
    main()
