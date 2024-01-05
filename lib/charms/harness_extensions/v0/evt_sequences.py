'''This was a library providing a utility for unit testing event sequences with the harness.
this charm library has been deprecated and is replaced by ops-scenario.
To learn more visit: https://github.com/canonical/ops-scenario
or ask on mattermost:
https://chat.charmhub.io/charmhub/channels/charm-dev
'''

# The unique Charmhub library identifier, never change it
LIBID = "884af95dbb1d4e8db20e0c29e6231ffe"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


import logging

logging.getLogger(__name__).warning(
    "DEPRECATION NOTICE: this charm library has been deprecated and is replaced by ops-scenario. \n"
    "To learn more visit: https://github.com/canonical/ops-scenario \n"
    "or ask on mattermost: \n"
    "https://chat.charmhub.io/charmhub/channels/charm-dev\n"
    " 'T was fun."
)

