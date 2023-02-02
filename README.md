# Github-Asana Bridge

Github Actions integration with Asana

*Status:* WIP/pre-production - unstable, incomplete and **not for general use**.

This repo enables Github Action integration with Asana in ways that are
suited to the MozMEAO workflow.

## Example usage

1. Set up your repo's secrets to make `ASANA_PAT` and `ASANA_PROJECT` available - both of these you get from the Asana side. Ideally, the PAT should be an Asana [service account](https://asana.com/guide/help/premium/service-accounts) token.

2. In `your-project/.github/workflows/choose-a-filename.yaml` add:

```code:yaml

name: "Github-Asana bridge"

on:
  issues:
    types:
      - opened

jobs:
  handle_issue:
    name: "Trigger following GH Issue change"
    uses: mozmeao/asana-github-bridge/.github/workflows/issue_handler.yaml@APPROPRIATE_VERISON_HERE
    with:
      issue-url: ${{ github.event.issue.html_url }}
      issue-title: ${{ github.event.issue.title }}
      issue-body: ${{ github.event.issue.body }}
      issue-timestamp: ${{ github.event.issue.updated_at }}
    secrets:
      ASANA_PAT: ${{ secrets.ASANA_PAT }}
      ASANA_PROJECT: ${{ secrets.ASANA_PROJECT }}
      REPO_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

More information will follow as functionality is checked and enabled.

----

LICENSE: [Mozilla Public License Version 2.0](LICENSE)
