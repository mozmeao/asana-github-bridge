# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from io import StringIO
from unittest import mock

from bin.manage_asana_task import (
    FLAG_ONLY_REACT_TO_ALL,
    FLAG_ONLY_REACT_TO_SPECIFIED_USERS,
    MESSAGE_UNABLE_TO_CREATE_ASANA_PERMALINK,
    _build_task_body,
    _get_default_asana_headers,
    _get_default_github_headers,
    _get_github_issue_field_gid,
    _may_bridge_to_asana,
    _transform_to_api_url,
    add_task_as_comment_on_github_issue,
    create_task,
    log,
    main,
)

import pytest


@pytest.mark.parametrize(
    "params, expected",
    (
        (("hello",), "hello\n"),
        (("hello", "world"), "hello world\n"),
    ),
)
@mock.patch("sys.stdout", new_callable=StringIO)
def test_log(mock_stdout, params, expected):
    log(*params)
    assert mock_stdout.getvalue() == expected


def test__get_default_asana_headers(monkeypatch):
    monkeypatch.setenv("ASANA_PAT", "test-pat-for-asana")

    assert _get_default_asana_headers() == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer test-pat-for-asana",
    }


def test__get_default_github_headers(monkeypatch):
    monkeypatch.setenv("REPO_TOKEN", "test-token-for-github")

    assert _get_default_github_headers() == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer test-token-for-github",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def test__get_github_issue_field_gid__env_var_present(monkeypatch):
    monkeypatch.setenv("ASANA_GITHUB_ISSUE_CUSTOM_FIELD_GID", "test-test-test")

    assert _get_github_issue_field_gid() == "test-test-test"


@pytest.mark.parametrize(
    "get_return_value, expected_gid",
    (
        (
            json.dumps(
                {
                    "data": {
                        "custom_field_settings": [
                            {
                                "custom_field": {
                                    "name": "Github Issue",
                                    "gid": "TEST_GID",
                                }
                            }
                        ]
                    }
                }
            ),
            "TEST_GID",
        ),
        (
            json.dumps(
                {
                    "data": {
                        "custom_field_settings": [
                            {
                                "custom_field": {
                                    "name": "NOT Github Issue",
                                    "gid": "OTHER_GID",
                                }
                            }
                        ]
                    }
                }
            ),
            "",
        ),
        (json.dumps({"data": {"custom_field_settings": []}}), ""),
        (json.dumps({"data": {}}), ""),
    ),
)
@mock.patch("bin.manage_asana_task.requests.get")
def test__get_github_issue_field_gid__no_env_var(
    mock_get,
    get_return_value,
    expected_gid,
):
    mock_resp = mock.Mock()
    mock_resp.status_code = 200
    mock_resp.text = get_return_value

    mock_get.return_value = mock_resp
    assert _get_github_issue_field_gid() == expected_gid


@mock.patch("bin.manage_asana_task.requests.get")
def test__get_github_issue_field_gid__404(mock_get):
    mock_resp = mock.Mock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp
    assert _get_github_issue_field_gid() == ""


@pytest.mark.parametrize(
    "issue_body, custom_gh_field_known, sanitization_expected",
    (
        ("## test body", True, False),
        ("## test body>", False, False),
        ("<script>alert('boo');</script>", True, True),
        ("<script>alert('boo');</script>", False, True),
    ),
)
def test__build_task_body(
    issue_body,
    custom_gh_field_known,
    sanitization_expected,
):
    html_body, content_changed_during_sanitization = _build_task_body(
        issue_body=issue_body,
        issue_url="https://example.com/luftballons/issues/99",
        custom_gh_field_known=custom_gh_field_known,
    )

    assert content_changed_during_sanitization == sanitization_expected

    if sanitization_expected:
        assert "<hr>\nNote: The original Issue contained content which cannot be displayed in an Asana Task" in html_body
    else:
        assert "<hr>\nNote: The original Issue contained content which cannot be displayed in an Asana Task" not in html_body

    if custom_gh_field_known:
        assert '<a href="https://example.com/luftballons/issues/99">Github</a>' not in html_body
    else:
        assert '<a href="https://example.com/luftballons/issues/99">Github</a>' in html_body


@pytest.mark.parametrize(
    "fake_gid, resp_status_code, description_changed",
    (
        ("fake-gid-value", 201, True),
        ("fake-gid-value", 201, False),
        ("fake-gid-value", 404, False),
        ("", 201, True),
        ("", 201, False),
        ("", 404, False),
    ),
)
@mock.patch("bin.manage_asana_task._build_task_body")
@mock.patch("bin.manage_asana_task._get_github_issue_field_gid")
@mock.patch("bin.manage_asana_task.requests.post")
@mock.patch("bin.manage_asana_task.log")
def test_create_task(
    mock_log,
    mock_post,
    mock__get_github_issue_field_gid,
    mock__build_task_body,
    fake_gid,
    resp_status_code,
    description_changed,
    monkeypatch,
):
    monkeypatch.setenv("ASANA_PROJECT", "fake-asana-project")

    mock__get_github_issue_field_gid.return_value = fake_gid
    mock__build_task_body.return_value = ("fake body", description_changed)

    fake_resp = mock.Mock()
    fake_resp.status_code = resp_status_code
    fake_resp.text = json.dumps({"data": {"permalink_url": "https://asana.example.com/task/1234"}})
    fake_resp.content = fake_resp.text.encode("utf-8")

    mock_post.return_value = fake_resp

    permalink, desc_changed = create_task(
        issue_url="https://example.com/luftballons/issues/99",
        issue_title="99 Red Balloons",
        issue_body="1980s classic",
    )
    assert desc_changed == description_changed
    if resp_status_code == 201:
        assert permalink == "https://asana.example.com/task/1234"
        mock_log.assert_called_once_with("Asana task created: https://asana.example.com/task/1234")
    else:
        assert permalink == MESSAGE_UNABLE_TO_CREATE_ASANA_PERMALINK
        mock_log.assert_called_once_with(fake_resp.content)


@pytest.mark.parametrize(
    "original_url,expected_url",
    (
        ("https://github.com/mozilla/bedrock", "https://api.github.com/repos/mozilla/bedrock"),
        ("https://gitlab.com/mozmeao/bedrock", "https://gitlab.com/mozmeao/bedrock"),
    ),
)
def test__transform_to_api_url(original_url, expected_url):
    assert _transform_to_api_url(original_url) == expected_url


@pytest.mark.parametrize(
    "github_desc_was_changed, repo_token, return_code",
    (
        (True, "test-token-for-github", 201),
        (True, "test-token-for-github", 404),
        (False, "test-token-for-github", 201),
        (False, "test-token-for-github", 404),
        ("irrelevant", "", "irrelevant"),
    ),
)
@mock.patch("bin.manage_asana_task.requests.post")
@mock.patch("bin.manage_asana_task.log")
def test_add_task_as_comment_on_github_issue(
    mock_log,
    mock_post,
    github_desc_was_changed,
    repo_token,
    return_code,
    monkeypatch,
):
    monkeypatch.setenv("REPO_TOKEN", repo_token)

    fake_resp = mock.Mock(name="fake-resp")
    fake_resp.text = "fake response text"
    fake_resp.status_code = return_code
    mock_post.return_value = fake_resp

    add_task_as_comment_on_github_issue(
        issue_api_url="https://api.github.com/example/luftballons/issues/123",
        task_permalink="https//asana.example.com/task/65656655665",
        github_description_was_changed_for_asana=github_desc_was_changed,
    )

    # TODO: make this nicer - not great to if/else here
    if not repo_token:
        mock_log.assert_called_once_with("No REPO_TOKEN found - cannot update Issue")
    else:
        assert mock_post.call_count == 1
        assert mock_post.call_args_list[0][0][0] == "https://api.github.com/example/luftballons/issues/123/comments"
        assert mock_post.call_args_list[0][1]["headers"] == {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {repo_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if return_code == 201:
            mock_log.assert_called_once_with("Asana task URL added in comment on original issue")
        else:
            assert mock_log.call_args_list[0][0][0] == "Commenting failed: fake response text"


@mock.patch("bin.manage_asana_task.log")
def test__may_bridge_to_asana__react_to_all(mock_log, monkeypatch):
    monkeypatch.setenv("ONLY_REACT_TO", FLAG_ONLY_REACT_TO_ALL)
    monkeypatch.setenv("REPO_TOKEN", "test-token-for-github")
    assert _may_bridge_to_asana(actor="alexander-testington", repo_info="example/luftballons") is True
    mock_log.assert_called_once_with("All Issues are being bridged to Asana.")


@pytest.mark.parametrize(
    "actor_username,actor_allowlist,expected_retval",
    (
        (
            "alexander-testington",
            "aaron-bug,alexander-testington,hercules-mulligan,",
            True,
        ),
        (
            "alexander-testington",
            "aaron-bug,eliza-testington,hercules-mulligan,",
            False,
        ),
        (
            "alexander-testington",
            None,
            False,
        ),
    ),
)
@mock.patch("bin.manage_asana_task.log")
def test__may_bridge_to_asana__react_to_specified_users(
    mock_log,
    monkeypatch,
    actor_username,
    actor_allowlist,
    expected_retval,
):
    monkeypatch.setenv("ONLY_REACT_TO", FLAG_ONLY_REACT_TO_SPECIFIED_USERS)
    monkeypatch.setenv("ACTOR_ALLOWLIST", actor_allowlist)
    assert _may_bridge_to_asana(actor=actor_username, repo_info="example/luftballons") is expected_retval
    if expected_retval is True:
        mock_log.assert_called_once_with(f"Actor {actor_username} is in the provided allowlist.")
    else:
        assert mock_log.call_count == 2
        mock_log.assert_has_calls(
            (
                mock.call(f"Actor {actor_username} is not in the provided allowlist."),
                mock.call("Bridging this issue to Asana is not allowed"),
            ),
            {},
        )


@mock.patch("bin.manage_asana_task.log")
def test__may_bridge_to_asana__react_to_set_to_nonsense(mock_log, monkeypatch):
    monkeypatch.setenv("ONLY_REACT_TO", "not-a-recognised-value")
    assert _may_bridge_to_asana(actor="alexander-testington", repo_info="example/luftballons") is False
    mock_log.assert_called_once_with("Bridging this issue to Asana is not allowed")


@mock.patch("bin.manage_asana_task._may_bridge_to_asana")
@mock.patch("bin.manage_asana_task.add_task_as_comment_on_github_issue")
@mock.patch("bin.manage_asana_task.create_task")
def test_main(
    mock_create_task,
    mock_add_task_as_comment_on_github_issue,
    mock__may_bridge_to_asana,
    monkeypatch,
):
    monkeypatch.setenv("REPO", "example/luftballons")
    monkeypatch.setenv("ACTOR", "alexander-testington")
    monkeypatch.setenv("ISSUE_URL", "https://example.com/luftballons/issues/99")
    monkeypatch.setenv("ISSUE_TITLE", "99 Red Balloons")
    monkeypatch.setenv("ISSUE_BODY", "1980s classic")

    mock_create_task.return_value = ("https://example.com/task/1", True)

    mock__may_bridge_to_asana.return_value = True

    main()

    mock__may_bridge_to_asana.assert_called_once_with(
        actor="alexander-testington",
        repo_info="example/luftballons",
    )
    mock_create_task.assert_called_once_with(
        issue_url="https://example.com/luftballons/issues/99",
        issue_title="99 Red Balloons",
        issue_body="1980s classic",
    )
    mock_add_task_as_comment_on_github_issue.assert_called_once_with(
        issue_api_url="https://example.com/luftballons/issues/99",  # NB not transformed cos not github URL in example
        task_permalink="https://example.com/task/1",
        github_description_was_changed_for_asana=True,
    )


@mock.patch("bin.manage_asana_task.log")
@mock.patch("bin.manage_asana_task._may_bridge_to_asana")
@mock.patch("bin.manage_asana_task.add_task_as_comment_on_github_issue")
@mock.patch("bin.manage_asana_task.create_task")
def test_main__not_allowed_to_bridge(
    mock_create_task,
    mock_add_task_as_comment_on_github_issue,
    mock__may_bridge_to_asana,
    mock_log,
    monkeypatch,
):
    monkeypatch.setenv("REPO", "example/luftballons")
    monkeypatch.setenv("ACTOR", "alexander-testington")
    monkeypatch.setenv("ISSUE_URL", "https://example.com/example/luftballons/issues/99")
    monkeypatch.setenv("ISSUE_TITLE", "99 Red Balloons")
    monkeypatch.setenv("ISSUE_BODY", "1980s classic")
    mock_create_task.return_value = ("https://example.com/task/1", True)
    mock__may_bridge_to_asana.return_value = False

    main()

    mock__may_bridge_to_asana.assert_called_once_with(
        actor="alexander-testington",
        repo_info="example/luftballons",
    )
    assert not mock_create_task.called
    assert not mock_add_task_as_comment_on_github_issue.called
    mock_log.assert_called_once_with(
        "alexander-testington is not in the allowlist of users who can trigger mirroring. Not mirroring this Issue to Asana"
    )
