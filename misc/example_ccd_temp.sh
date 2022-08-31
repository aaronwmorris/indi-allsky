#!/bin/bash

# Example of an external temperature script for indi-allsky
# The first line to STDOUT should be a number
# Additional lines are ignored
# Any info sent to STDERR is also ignored

TEMP_C=-5.111

echo "STDERR is ignored" >&2

# first line to STDOUT must contain a number with no additional details
# number is assumed to be celcius

printf "%0.2f\n" $TEMP_C  # formatting is not necessary, this is just an example

# This would also be valid
#echo "$TEMP_C"


echo "Any additional lines are ignored"
