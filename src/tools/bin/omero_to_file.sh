#!/bin/sh
# Assumes the current path is configured for OMERO cli.
# Add the set-up for archiving.
export OMERO_TOOLS=/OMERO/tools
export PYTHONPATH=$PYTHONPATH:$OMERO_TOOLS/lib/python
export PATH=$PATH:$OMERO_TOOLS/bin
process_archive_images.py
archive_to_file.py
