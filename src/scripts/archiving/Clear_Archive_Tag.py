#!/usr/bin/python
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
This removes the archiving tag annotation from all the images that marks them
for archiving. This script is used to prevent images marked in error for
archiving from being archived. If the archiving process has started then the
archiving tag will have been changed and the process cannot be stopped.
"""

import locale
locale.setlocale(locale.LC_ALL, 'en_GB.UTF8')

import omero.scripts as scripts
from omero.gateway import BlitzGateway, TagAnnotationWrapper
from omero.rtypes import *  # noqa
from omero.sys import Parameters

# For command-line support
from optparse import OptionParser, OptionGroup

import gdsc.omero

PARAM_DATATYPE = "Data_Type"
PARAM_IDS = "IDs"

def close(conn):
    """
    Close the connection

    @param conn: The connection
    """
    if conn:
        conn.close()

def getUserId(description):
    """
    Get the user Id from the tag description

    @param description: The tag description
    """
    tokens = description.split(':')
    if tokens and len(tokens) > 2:
        try:
            return long(tokens[1])
        except:
            pass
    return 0

def run(conn, params):
    """
    For each image defined in the script parameters tagged with an annotation to
    mark them for archiving, remove the tag.

    @param conn:   The BlitzGateway connection
    @param params: The script parameters
    """

    # print "Parameters = %s" % params

    images = []
    objects = conn.getObjects(params[PARAM_DATATYPE],
                              params.get(PARAM_IDS, [0]))
    if params[PARAM_DATATYPE] == 'Dataset':
        for ds in objects:
            images.extend(list(ds.listChildren()))
    else:
        images = list(objects)

    # Remove duplicate images in multiple datasets
    seen = set()
    images = [x for x in images if x.id not in seen and not seen.add(x.id)]

    print("Processing %s image%s" % (
        len(images), len(images) != 1 and 's' or ''))

    if not images:
        return (0,0)

    linked_id = conn.getEventContext().userId
    linked_omename = conn.getEventContext().userName

    qs = conn.getQueryService()

    # This script will attempt to remove all tags with the name
    # TAG_TO_ARCHIVE and TAG_ARCHIVE_NOTE.
    # If the tag is not owned by the user this will fail.
    # The Archive_Images.py script allows admin or group owners
    # to tag images as the image owner. Here we allow them to untag
    # images.

    # Obtain the image owner and the group.
    # This should be the same for all images. It may not be if running as
    # a command line program. When running through a script via OMERO.insight
    # then the scripting framework should prevent multiple groups. Multiple
    # owner may occur if a user creates a composite dataset.
    oids = set()
    gids = set()
    for x in images:
        oids.add(x.getOwner().id)
        gids.add(x.getDetails().getGroup().id)
    if len(oids) > 1:
        raise Exception("ERROR : Untagging not supported for multiple image owners: %s" % oids)
    if len(gids) > 1:
        raise Exception("ERROR : Untagging not supported for multiple groups: %s" % gids)

    owner_id = oids.pop()
    group_id = gids.pop()

    # Elevate permissions if required.
    conn2 = None
    conn3 = None
    if owner_id != linked_id:
        print("User %s removing tags from user %s images" % (linked_id, owner_id))
        # Check for allowed permissions
        if not conn.isAdmin():
            # Must be the group owner
            group = conn.getObject('ExperimenterGroup', group_id)
            # The first list from groupSummary is the group leaders
            if not any(x.id == linked_id for x in group.groupSummary()[0]):
                raise Exception("ERROR : Untagging other users images requires group leader permissions")
            print("Elevating user %s permissions" % linked_id)
            # Create admin connection
            conn2 = BlitzGateway(gdsc.omero.USERNAME, gdsc.omero.PASSWORD,
                                 host=gdsc.omero.HOST, port=gdsc.omero.PORT)
            if not conn2.connect() or not conn2.isAdmin():
                raise Exception("Failed to elevate to admin connection: %s" %
                                conn.getLastError())
            conn = conn2

        # conn is now an admin connection
        # conn2 will be closed manually on function return

    # Use the actual SERVICE_OPTS
    service_opts = conn.SERVICE_OPTS  #.copy()
    service_opts.setOmeroGroup(group_id)

    # No need to find if any tag exists. Just search for annotations.

    # Remove the to-archive tag from all the images
    # Get the link Ids and then delete objects
    hql = "select link.id " \
            "from ImageAnnotationLink link " \
            "where link.child.class is MapAnnotation " \
            "and link.child.name in (:value) " \
            "and link.parent.id in (:values)"

    p = Parameters()
    p.map = {}
    p.map["values"] = rlist([rlong(x.id) for x in images])
    p.map["value"] = rlist([rstring(gdsc.omero.TAG_TO_ARCHIVE), rstring(gdsc.omero.TAG_ARCHIVE_NOTE)])

    link_ids = [x[0].val for x in qs.projection(hql, p, service_opts)]

    count = len(link_ids)
    if count:
        print("Removing tag:", gdsc.omero.TAG_TO_ARCHIVE)
        print("Removing tag:", gdsc.omero.TAG_ARCHIVE_NOTE)

        handle = conn.deleteObjects('ImageAnnotationLink', link_ids)
        cb = omero.callbacks.CmdCallbackI(conn.c, handle)
        while not cb.block(500):
            log(".")
        r = cb.getResponse()
        cb.close(True)
        if isinstance(r, omero.cmd.ERR):
            print("Failed to remove links: %s" % cb.getResponse())
            close(conn2)
            return (0,count)

    close(conn2)
    return (count,0)


def summary(removed, error):
    """Produce a summary message of the tag counts"""
    msg = "Removed %d : Error %s" % (removed, error)
    return msg


def run_as_program():
    """
    Testing function to allow the script to be called outside of the OMERO
    scripting environment. The connection details must be valid with permissions
    to allow a tag to be added to the specified IDs.
    """

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Program to clear the tag marking images/datasets for "
                                      "file archiving",
                          add_help_option=True, version="%prog 1.0")

    parser.add_option("--datatype", dest="datatype", default="Image",
                     help="Datatype: Image (default); Dataset")

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

    (options, args) = parser.parse_args()

    # Collect all the integer arguments
    ids = []
    for arg in args:
        if arg.isdigit():
            ids.append(int(arg))

    if not ids:
        print("ERROR: No IDs")
        sys.exit(1)

    params = {}
    params[PARAM_IDS] = ids
    params[PARAM_DATATYPE] = 'Dataset' if options.datatype == 'Dataset' else 'Image'

    conn = None
    try:
        print("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        print( "Connecting to OMERO ...")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        # Allow all groups
        conn.SERVICE_OPTS.setOmeroGroup(-1)

        (removed, error) = run(conn, params)

        print (summary(removed, error))
    except Exception as e:
        print("ERROR: An error occurred: %s" % e)
    finally:
        if conn:
            conn.close()


def run_as_script():
    """
    The main entry point of the script, as called by the client via the
    scripting service, passing the required parameters.
    """
    dataTypes = [rstring('Dataset'), rstring('Image')]

    client = scripts.client('Clear_Archive_Tag.py', """\
Clear the tag marking images for archiving.

Warning:

Images marked for archiving will have a TO-ARCHIVE tag applied to them.
This script is used to remove the tag when it was applied in error.

Note: Once the archiving process has started the tag will be changed to
ARCHIVE-PENDING or ARCHIVED (when complete). If this occurs then the process
cannot be stopped.

See: http://www.sussex.ac.uk/gdsc/intranet/microscopy/omero/scripts/cleararchivetag""",  # noqa

    scripts.String(PARAM_DATATYPE, optional=False, grouping="1.1",
        description="The data you want to work with.", values=dataTypes,
        default="Image"),

    scripts.List(PARAM_IDS, optional=True, grouping="1.2",
        description="List of Dataset IDs or Image IDs").ofType(rlong(0)),

    version="1.0",
    authors=["Alex Herbert", "GDSC"],
    institutions=["University of Sussex"],
    contact="a.herbert@sussex.ac.uk",
    )

    try:
        conn = BlitzGateway(client_obj=client)

        # Process the list of args above.
        params = {}
        for key in client.getInputKeys():
            if client.getInput(key):
                params[key] = client.getInput(key, unwrap=True)

        # Call the main script - returns the number of images
        (removed, error) = run(conn, params)

        print("Removed  : %s" % removed)
        print("Error    : %s" % error)

        # Combine the totals for the summary message
        msg = summary(removed, error)
        client.setOutput("Message", rstring(msg))
    except Exception as x:
        # Special case of invalid tagging permissions is a
        # omero.ReadOnlyGroupSecurityViolation which has a useful message attribute
        client.setOutput("Message", rstring(getattr(x, 'message', str(x))))
    finally:
        client.closeSession()

if __name__ == "__main__":
    """
    Python entry point
    """
    if len(sys.argv) > 1:
        run_as_program()
    else:
        run_as_script()
