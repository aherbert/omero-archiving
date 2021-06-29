#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.

# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
# OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.
# ------------------------------------------------------------------------------

"""
This script processes all the files listed in the archive registers and checks
the images still exist in OMERO.
"""
import sys
import os
import configparser

from optparse import OptionParser, OptionGroup

from omero.gateway import BlitzGateway
from omero.rtypes import *  # noqa
from omero.sys import Parameters, Filter

import gdsc.omero

###############################################################################


def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Check if archived files' source images "
                                      "exist in OMERO",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_log", dest="archive_log",
                     default=gdsc.omero.ARCHIVE_LOG,
                     help="Directory for archive logs [%default]")
    group.add_option("--to_archive", dest="to_archive", 
                     default=gdsc.omero.TO_ARCHIVE_REGISTER,
                     help="To-Archive register [%default]")
    group.add_option("--archived", dest="archived", 
                     default=gdsc.omero.ARCHIVED_REGISTER,
                     help="Archived register [%default]")
    parser.add_option_group(group)

    group = OptionGroup(parser, "OMERO")
    group.add_option("-u", "--username", dest="username",
                     default=gdsc.omero.USERNAME,
                     help="OMERO username [%default]")
    group.add_option("-p", "--password", dest="password",
                     default=gdsc.omero.PASSWORD, help="OMERO password")
    group.add_option("--host", dest="host", default=gdsc.omero.HOST,
                     help="OMERO host [%default]")
    group.add_option("--port", dest="port", default=gdsc.omero.PORT,
                     help="OMERO port [%default]")
    parser.add_option_group(group)
    
    return parser

###############################################################################

def log(msg):
    """
    Print a message
    @param msg: The message
    """
    print(msg)
    
def error(msg):
    """
    Print an error message
    @param msg: The message
    """
    print("ERROR:", msg)
    
def die(msg):
    """
    Print an error then exit
    @param msg: The message
    """
    print("FATAL:", msg)
    sys.exit(1)

###############################################################################

def pleural(count):
    """
    Convenience method to return an s if the count is not 1
    @param count: The count
    """
    return '' if count == 1 else 's'

def check_images(conn, paths, name, ids):
    """
    Check if the listed images still exist in OMERO
    @param conn: The OMERO connection
    @param paths: The path to each file
    @param name: The name of the set
    @param ids: The image ID asscociated with each file
    """
    if not ids:
        return
    
    # List all archived files associated with each image id
    map = {}
    for (path, id) in zip(paths, ids):
        if id in map:
            map[id].append(path)
        else:
            map[id] = [path]
    
    # Check if they are in OMERO
    hql = "select id " \
            "from Image " \
            "where id in (:values)"
        
    params = Parameters()
    params.map = {}
    params.map["values"] = rlist([rlong(id) for id in map])

    qs = conn.getQueryService()
    service_opts = conn.SERVICE_OPTS.copy()
    # Generic group for query across all of OMERO
    service_opts.setOmeroGroup(-1)
    
    found = set()
    for x in qs.projection(hql, params, service_opts):
        id = x[0].val
        found.add(id)
    
    # Report which images were not found in OMERO
    for id in map:
        if id not in found:
            missing = missing + 1
            error("Missing image %d : %s" % (id, str(map[id])))
            
    total = len(found)
    count = len(map)
    log("Found '%s': %d / %d image%s" % (name, total, count,   
                                         gdsc.omero.pleural(count)))
    
def list_images(name, items):
    """
    Build a list of the source image Ids using the .ark files
    @param name: The name of the set
    @param items: The set of archive paths
    """
    global options
    ids = []
    paths = []
    
    for path in items:
        ark_file = gdsc.omero.get_ark_path(options.archive_log, path)
        if not os.path.isfile(ark_file):
            error("Missing archive record for '%s' file: %s" % (name, path))
        else:
            config = configparser.RawConfigParser()
            config.read(ark_file)
            paths.append(path)
            ids.append(config.getint(gdsc.omero.ARK_SOURCE, 'image'))
    
    total = len(paths)
    count = len(items)
    log("Validating '%s': %d / %d image%s" % (name, total, count, 
                                             gdsc.omero.pleural(count)))
    
    return (paths, ids)

# Gather our code in a main() function
def main():
    parser = init_options()
    global options
    (options, args) = parser.parse_args()

    try:
        # Open the registers
        register = gdsc.omero.Register(options.to_archive)
        archived = gdsc.omero.Register(options.archived)

    except Exception as e:
        die("An error occurred: %s" % e)
        
    # Check for files in the To-Archive and Archived register
    intersect = register.items.intersection(archived.items)
    if intersect:
        size = len(intersect)
        error("%d file%s already archived, ignoring" % (size, 
              '' if size == 1 else 's'))
        register.remove_list(list(intersect))

    conn = None
    try:
        # Build a list of all the source images for the paths
        (paths1, ids1) = list_images('To archive', register.items)
        (paths2, ids2) = list_images('Archived', archived.items)
        
        # Connect to OMERO
        log("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        log( "Connecting to OMERO ...")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())
        
        if not conn.isAdmin():
            die("Require ADMIN privaledges")

        check_images(conn, paths1, 'To archive', ids1)
        check_images(conn, paths2, 'Archived', ids2)

    except Exception as e:
        die("An error occurred: %s" % e)
    finally:
        if conn:
            conn.close()

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
