# Github-Asana Bridge

Github Actions integration with Asana

*Status:* Alpha - works, but sill in development

This repo enables Github Action integration with Asana in ways that are suited to the MozMEAO workflow.

## Current behaviour

* When an Issue is created in Github (or given certain label -- see examples), a corresponding Asana Task is created:
  * Both use the same title
  * If there's a description in the issue, a sanitised version of it is used as the body of the Asana task. (Asana [only allows a limited subset of HTML elements](https://developers.asana.com/docs/rich-text#reading-rich-text))
  * If the Task has a custom field named "Github Issue", the URL for the GH task is inserted there, else it's appended to the body of the task.
  * A comment is added to the original GH Issue, with a link to the Asana Task it has spawned - this is to close the loop and allow easy discovery from both sides of the bridge.

* By default, only Issues created/labelled by members of the same org that the caller repo is in will be mirrored to Asana. This prevents a spam risk if the Action is used in a public repo. Configuration allows this to be tightened to only team members associated with the caller repo, or loosened to trigger for anyone allowed to make an Issue.

Loose roadmap:

* ~Tests for current behaviour, to clear the way for easy code contributions~ DONE
* Plug into coverage-measuring tool, to clear the way for easy code contributions
* Support closing Asana tasks when the GH Issue is closed
* Limit scope to issues with certain labels
* Automatically add PR to Asana Task if associated with the GH issue (the official Asana Github integration does this, but it's something we could roll in here and keep just one integration going)
* Add the new Asana task to a particular (custom) section (e.g. Inbox / Backlog)
* Auto-commenting on the Asana Task if the GH issue is edited - this may be a reasonable way to avoid keeping main task body in sync, which brings sync/version challenges

## Example usage

1. Set up your repo's secrets to make `ASANA_PAT` and `ASANA_PROJECT` available - both of these you get from the Asana side. Ideally, the PAT should be an Asana [service account](https://asana.com/guide/help/premium/service-accounts) token. You can get the Project ID from the URL of the project.

2. Ideally using a service account, create a Github Personal Access Token (e.g. called `ASANA_GITHUB_BRIDGE_TOKEN`) with these permissions:
    * `repo: public_repo` - to be able to comment on the original Issue _for a public repository_. If this is not present, the commenting with the Asana link will not happen, but the copy to Asana will. If the repo is private, you will likely need to add to the full `repo` scope to be able to support comments. The output of the GH Action will show you if the token has sufficient scope.

    If you are using SSO remember to authorize that token for access.

    If you do not want to use the comment-back behaviour and you are happy to react to Issues from anyone/all users, you can just set the value of the `REPO_TOKEN` secret to that of `secrets.GITHUB_TOKEN` in your config - see below.

3. In `your-project/.github/workflows/choose-a-filename.yaml` add one of these two

```code:yaml

name: "Open Asana Task when GH Issue is created"

on:
  issues:
    types:
      - opened

jobs:
  handle_issue:
    name: "Trigger following GH Issue creation"
    uses: mozmeao/asana-github-bridge/issue-handler@v1.1
    with:
      ONLY_REACT_TO: specified-users   # optional - see issue_handler.yaml
      ACTOR_ALLOWLIST: usernameA,userB,userC
      ASANA_PAT: ${{ secrets.ASANA_PAT }}
      ASANA_PROJECT: ${{ secrets.ASANA_PROJECT }}
      REPO_TOKEN: ${{ secrets.ASANA_GITHUB_BRIDGE_TOKEN }}  # see point 2 above
      TAG: v1.1  # version of the bridge to use - see the repo for tags

```

or

```code:yaml

name: "Open Asana Task if a GH Issue is labelled with 'Asana'"

on:
  issues:
    types:
      - labelled

jobs:
  handle_issue:
    if: github.event.label.name == 'Asana'
    name: "Trigger after specific GH label was added"
    uses: mozmeao/asana-github-bridge/issue-handler@v1.1
    with:
      ONLY_REACT_TO: specified-users   # optional - see issue_handler.yaml
      ACTOR_ALLOWLIST: usernameA,userB,userC
      ASANA_PAT: ${{ secrets.ASANA_PAT }}
      ASANA_PROJECT: ${{ secrets.ASANA_PROJECT }}
      REPO_TOKEN: ${{ secrets.ASANA_GITHUB_BRIDGE_TOKEN }}  # see point 2 above
      TAG: v1.1  # version of the bridge to use - see the repo for tags

```

More information will follow as functionality is checked and enabled.

----

LICENSE: [Mozilla Public License Version 2.0](LICENSE)
