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
This tags all the images with an annotation to mark them for archiving
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
PARAM_EXPIRY = "Expiry"
PARAM_NOTES = "Description"

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
    For each image defined in the script parameters tag with an annotation to
    mark them for archiving

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
        return (0,0,0)

    # TODO
    # Allow group owners with read permissions the ability to tag
    # images of members of the group.
    
    linked_id = conn.getEventContext().userId
    linked_omename = conn.getEventContext().userName

    qs = conn.getQueryService()

    # Use the actual SERVICE_OPTS so that when we set the group it is
    # correct when saving a new tag
    service_opts = conn.SERVICE_OPTS  #.copy()
    service_opts.setOmeroGroup(conn.getEventContext().groupId)

    # List all the images which already have the tag or are already in the
    # archive process
    hql = "select distinct link.parent.id " \
            "from ImageAnnotationLink link " \
            "where link.child.class is MapAnnotation " \
            "and link.child.name in (:tags) " \
            "and link.parent.id in (:values)"

    p = Parameters()
    p.map = {}
    tags = [gdsc.omero.TAG_TO_ARCHIVE, gdsc.omero.TAG_PENDING, gdsc.omero.TAG_ARCHIVED]
    p.map['tags'] = rlist([rstring(x) for x in tags]) 
    p.map["values"] = rlist([rlong(x.id) for x in images])
    
    ignore = set()
    for result in qs.projection(hql, p, service_opts):
        ignore.add(result[0].val)

    # Tag all the remaining images with the TO-ARCHIVE tag
    links = []
    for x in images:
        if x.id in ignore:
            continue
        link = omero.model.ImageAnnotationLinkI()
        link.parent = omero.model.ImageI(x.id, False)
        # link.child is set later when we know there are links to create
        links.append(link)

    existing = len(ignore)
    
    if not links:
        return (0, existing, 0)

    # Find the to-archive tag
    tag_id = 0
    tags = list(conn.getObjects(
            "MapAnnotation", 
            attributes={'name':gdsc.omero.TAG_TO_ARCHIVE,"ns":"archiving"})
    )

    # Discarding any that can not be linked
    # This is when the group is read-only and the querying user is not
    # the owner of the tag
    for tag in tags:
        # Check the annotation class since the HQL was returning
        # BooleanAnnotationWrapper previously created with the same name
        if (tag.canLink() and 
            type(tag) == omero.gateway.MapAnnotationWrapper and 
            getUserId(tag.getDescription()) == linked_id):
            tag_id = tag.id
            break
    
    if not tag_id:
        # Create tag if necessary
        tag = omero.gateway.MapAnnotationWrapper(conn)
        tag.setName(gdsc.omero.TAG_TO_ARCHIVE)
        tag.setNs("archiving")
        tag.setDescription("Owner : " + str(linked_id) + " : " + 
                            linked_omename)
        tag.setValue([[gdsc.omero.TAG_TO_ARCHIVE,"True"]])
        tag.save()
        tag_id = tag.getId()
        if tag_id == 0:
            print("ERROR : Unable to find tag", gdsc.omero.TAG_TO_ARCHIVE)
            return (0,existing,0)

    # Add the tag to the links
    for link in links:
        link.child = omero.model.MapAnnotationI(tag_id, False)

    # Add the archive notes
    tag = omero.gateway.MapAnnotationWrapper(conn)
    tag.setName(gdsc.omero.TAG_ARCHIVE_NOTE)
    tag.setNs("archiving")
    tag.setDescription("Owner : " + str(linked_id) + " : " + 
                        linked_omename)
    tag.setValue([['Owner id',str(linked_id)],
                  ['Owner',linked_omename],
                  [PARAM_EXPIRY,str(params[PARAM_EXPIRY])],
                  [PARAM_NOTES,params[PARAM_NOTES]]])
    tag.save()
    tag_id2 = tag.getId()
    if tag_id2 == 0:
        print("ERROR : Unable to create tag", gdsc.omero.TAG_ARCHIVE_NOTE)
        return (0, existing, 0)

    links2 = []
    for x in images:
        if x.id in ignore:
            continue
        link = omero.model.ImageAnnotationLinkI()
        link.parent = omero.model.ImageI(x.id, False)
        link.child = omero.model.MapAnnotationI(tag_id2, False)
        links2.append(link)
    
    print("Applying tag:", tag_id2, gdsc.omero.TAG_ARCHIVE_NOTE)

    # Bulk apply the archive note. If this fails then no changes
    # have been committed.
    try:
        conn.getUpdateService().saveArray(links2, service_opts)
    except omero.ValidationException as x:
        print("ERROR : Unable to create archive notes", x)
        return (0, existing, 0)

    # Here we have added an archive note. But the images are not yet marked
    # for archiving. Try and mark the images in bilk and fall back to marking
    # them individually if this fails.
    print("Applying tag:", tag_id, gdsc.omero.TAG_TO_ARCHIVE)

    new = 0
    error = 0

    try:
        # Will fail if any of the links already exist
        conn.getUpdateService().saveArray(links, service_opts)
        new = len(links)
    except omero.ValidationException as x:
        # This will occur if the user has modified the tag landscape outside
        # of the script while running. Not likely to happen, but possible.
        # Try to link each image
        for link in links:
            try:
                # Service Opts must be in the correct group
                conn.getUpdateService().saveAndReturnObject(link, service_opts)
                new = new + 1
            except omero.ValidationException as x2:
                # ValidationException is thrown if the link already exists
                print('Failed to tag image:', link.parent.getId())
                error = error + 1

    return (new, existing, error)


def summary(new, existing, error):
    """Produce a summary message of the tag counts"""
    msg = "New %d : Existing %s : Error %s" % (new, existing, error)
    return msg


def run_as_program():
    """
    Testing function to allow the script to be called outside of the OMERO
    scripting environment. The connection details must be valid with permissions
    to allow a tag to be added to the specified IDs.
    """
    
    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Program to tag images/datasets for "
                                      "file archiving",
                          add_help_option=True, version="%prog 1.0")

    parser.add_option("--datatype", dest="datatype", default="Image", 
                     help="Datatype: Image (default); Dataset")
    parser.add_option("--expiry", dest="expiry", type="int", default="0",
                     help="Expiry date for the archive in years. Used during archive review")
    parser.add_option("--description", dest="description",
                     help="Add a description, for example to identify archive purpose")
   
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
    params[PARAM_EXPIRY] = options.expiry
    params[PARAM_NOTES] = options.description

    conn = None
    try:
        print("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        print( "Connecting to OMERO ...")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        (new, existing, error) = run(conn, params)

        print (summary(new, existing, error))
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

    client = scripts.client('Archive_Images.py', """\
Tag the images for archiving.

Warning:

Images tagged for archiving will be moved to the archive by an archiving
process. 

When achiving is complete the images MAY NOT BE AVAILABLE TO VIEW in 
OMERO, or may have a delay when viewing.

See: http://www.sussex.ac.uk/gdsc/intranet/microscopy/omero/scripts/archiveimages""",  # noqa

    scripts.String(PARAM_DATATYPE, optional=False, grouping="1.1",
        description="The data you want to work with.", values=dataTypes,
        default="Image"),

    scripts.List(PARAM_IDS, optional=True, grouping="1.2",
        description="List of Dataset IDs or Image IDs").ofType(rlong(0)),

    scripts.Int(PARAM_EXPIRY, optional=False, grouping="1.3",
        description="Expiry date for the archive (in years). Used during archive review. Use 0 for never.",
        default="0"),

    scripts.String(PARAM_NOTES, optional=True, grouping="1.4",
        description=("Add a description, for example to identify archive purpose")),

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
        (new, existing, error) = run(conn, params)

        print("New      : %s" % new)
        print("Existing : %s" % existing)
        print("Error    : %s" % error)

        # Combine the totals for the summary message
        msg = summary(new, existing, error)
        client.setOutput("Message", rstring(msg))
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
