#!/bin/bash

# Example of an external temperature script for indi-allsky
# STDOUT and STDERR are ignored
#
# The json output file is set in the environment variable TEMP_JSON

set -o errexit  # exit on any error
set -o nounset  # exit on any unset variable


# shellcheck disable=SC2317
function sigint_handler() {
    # this prevents a keyboard interrupt from stopping the script
    true
}
trap sigint_handler SIGINT


#############
### START ###
#############


TEMP_C=-5.111


# data file is communicated via environment variable
if [ -z "${TEMP_JSON:-}" ]; then
    echo "TEMP_JSON environment variable is not defined"
    exit 1
fi


# write json data
jq --null-input --argjson temp_c "$TEMP_C" '.temp = $temp_c' '{}' > "$TEMP_JSON"


# you could also just use a string as long as it is valid json
#echo "{ \"temp\" : $TEMP_C }" | jq > $TEMP_JSON


# script must return exit code 0 for success
exit 0
