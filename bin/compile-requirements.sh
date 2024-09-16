#!/bin/bash

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -exo pipefail

pip install -U uv
# start with a clean slate each time
rm requirements.txt
uv pip compile --generate-hashes --no-strip-extras requirements.in -o requirements.txt
