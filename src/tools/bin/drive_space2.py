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
This script builds a list of the drive usage for each user. Reports the users
current group but does not total up file usage per group. Targets OMERO 5.

Based on the code in:

lib/python/omeroweb/webadmin/controller/drivespace.py
components/tools/OmeroWeb/omeroweb/webadmin/views.py

"""
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from email.utils import formatdate
import re
import time
import locale
locale.setlocale(locale.LC_ALL, '')
from optparse import OptionParser
from optparse import OptionGroup
from datetime import datetime
from datetime import timedelta

import omero
from omero.gateway import BlitzGateway
from omero.rtypes import *  # noqa

import gdsc.omero
from gdsc.omero import convert

DATE_FORMAT = "%a, %d %b %Y %H:%M:%S"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
FILENAME_FORMAT = "%Y-%m-%d_%H%M%S.csv"

ARCHIVE_LIMIT = 2 * 1024 * 1024 * 1024

###############################################################################

def init_options():
    """Initialise the program options"""
    parser = OptionParser(
        usage="usage: %prog [options] e-mail [e-mail ...]",
        description="Program to build a list of drive usage per user (OMERO 5)",
        add_help_option=True, version="%prog 1.0")

    parser.add_option(
        "--report", dest="report",
        help="Previous usage file (used to generate incremental usage)")
    parser.add_option(
        "-b", "--big_ids", dest="big_ids",
        help="File listing original file IDs that are truncated to 2GB")
    parser.add_option(
        "-s", "--silent", dest="silent", action="store_true", default=False,
        help="Do not print report (requires e-mail addresses)")
    parser.add_option(
        "--delimiter", dest="delimiter", default=':',
        help="Report column delimiter [%default]")
    parser.add_option(
        "-i", "--ids", dest="ids", default='',
        help="List specific user IDs (comma-delimited) [%default]")
    parser.add_option(
        "--quota", dest="quota",
        help="Quota file")
    parser.add_option("--quota_example", dest="quota_example",
                      action="store_true", default=False,
                      help="Print example quota file")
    parser.add_option("--only_quota", dest="only_quota", action="store_true",
                      default=False, help="Only user IDs in the quota file")

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
    group.add_option("-g", "--group", dest="group", action="store_true",
                     default=False, help="Add group name [%default]")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Report")
    group.add_option("--title",
                     default='OMERO Usage', help="Report title [%default]")
    group.add_option("--dir",
                     help="Archive directory (for saving usage report)")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Debugging")
    group.add_option("-d", "--debug", dest="debug", action="store_true",
                     default=False, help="debug info")
    group.add_option("-v", action="count", dest="verbosity", help="verbosity")
    parser.add_option_group(group)

    return parser

###############################################################################


def get_bytes(text):
    result = re.match('\s*(\d+)\s*(\S*)', text)
    if result:
        bytes = int(result.group(1))
        if result.group(2):
            suffix = result.group(2).lower()
            if suffix == 'b':
                pass
            elif suffix == 'kb':
                bytes = bytes << 10
            elif suffix == 'mb':
                bytes = bytes << 20
            elif suffix == 'gb':
                bytes = bytes << 30
            elif suffix == 'tb':
                bytes = bytes << 40
            elif suffix == 'pb':
                bytes = bytes << 50
            return bytes

    raise Exception('Cannot parse byte string: ' + text)


def read_quota_file(options):
    quota = dict()
    if options.quota:
        f = open(options.quota, "r")
        mode = 0

        for line in f:
            if re.match("^#", line):
                continue
            line2 = line.lower()
            if line2.startswith('[group'):
                mode = 1
                continue
            if line2.startswith('[user'):
                mode = 2
                continue

            data = line.split(':')
            if len(data) < 2:
                continue

            if mode == 1:
                gid = data[0].strip()
                size = get_bytes(data[1])
                dic = dict()
                dic['id'] = gid
                dic['size'] = size
                dic['users'] = []
                quota[gid] = dic

            if mode == 2:
                gid = data[2].strip()
                oid = int(data[0].strip())
                if gid in quota:
                    quota[gid]['users'].append(oid)

        f.close()

    return quota


def send_email(sender, receivers, subject, message, attach_text):
    """
    Send an e-mail message

    @param sender:    The sender e-mail address
    @param receivers: List of the receivers e-mail addresses
    @param subject:   The email subject
    @param message:   The text message
    @param attach_text:  A text mail attachment

    """
    if not receivers:
        return

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = ','.join(receivers)
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(message))

    if attach_text:
        part = MIMEBase('text', "csv")
        part.set_payload(attach_text)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
                        'attachment; filename="report.csv"')
        msg.attach(part)

    smtpObj = smtplib.SMTP('localhost')
    smtpObj.sendmail(sender, receivers, msg.as_string())
    smtpObj.quit()


def convert_rtime(time):
    date = datetime.fromtimestamp(time.val / 1000)
    return date.strftime(TIMESTAMP_FORMAT)


def users_data(conn, options):
    """
    Returns a list of: {"data":<Bytes>, "id": <user id>, "label": <Full Name>,
    "group": <Default Group Name>}
    """

    # Get experimenter details
    exps = dict()
    exps_ids = dict()
    for e in list(conn.findExperimenters()):
        exps[e.id] = [e.getFullName(),
                      conn.getDefaultGroup(e.id).getName()]
        exps_ids[e.getName()] = e.id

    # Get usage across all groups
    queryService = conn.getQueryService()
    ctx = conn.SERVICE_OPTS.copy()
    ctx.setOmeroGroup(-1)

    pixelsQuery = "select owner.id as id, sum(cast( p.sizeX as double ) * " \
        "p.sizeY * p.sizeZ * p.sizeT * p.sizeC) as usage, pt.value " \
        "from Pixels p join p.pixelsType as pt join p.details.owner as owner " \
        "join p.image i left outer join " \
        "i.fileset f " \
        "where f is null"

    filesQuery = "select owner.id, sum(origFile.size) as usage from " \
        "OriginalFile as origFile " \
        "join origFile.details.owner as owner"

    # Add filter for experimenter(s)
    ids = []
    params = omero.sys.ParametersI()
    if options.ids:
        pixelsQuery += " and owner.id in (:ids)"
        filesQuery += " where owner.id in (:ids)"
        # Create the Id list
        for name in options.ids.split(','):
            # Accept login names or user IDs
            if name.isdigit():
                ids.append(rlong(name))
            elif name in exps_ids:
                ids.append(rlong(exps_ids[name]))
        if not ids:
            raise Exception("No valid user IDs!")
        ids = rlist(ids)
        params.add('ids', ids)

    pixelsQuery += " group by owner.id, pt.value order by owner.id"
    filesQuery += " group by owner.id order by owner.id"

    # Iterate over the full set of images
    usage_map = dict()

    # queryService.projection will return a set of rows of n columns

    # Calculate disk usage via Pixels
    result = queryService.projection(pixelsQuery, params, ctx)
    for row in result:
        oid = row[0]._val
        p_size = row[1]._val
        # Convert raw pixels to bytes
        p_size = p_size * gdsc.security.bytes_per_pixel(row[2]._val)
        usage_map[oid] = usage_map.get(oid, 0) + p_size
        if options.verbosity:
            print("%s : %s : Pixels Size %s (%s)" % (
                oid, exps[oid][0],
                locale.format('%d', p_size, True),
                convert(p_size, 1)))

    # Now get Original File usage
    result = queryService.projection(filesQuery, params, ctx)
    for row in result:
        oid = row[0]._val
        p_size = row[1]._val
        usage_map[oid] = usage_map.get(oid, 0) + p_size
        if options.verbosity:
            print("%s : %s : Files Size %s (%s)" % (
                oid, exps[oid][0],
                locale.format('%d', p_size, True),
                convert(p_size, 1)))

    # Subtract all OriginalFiles that are truncated. These can be found using:
    # find /OMERO/Files -size +2147483647c -exec ls -l {} \; > /tmp/big_files
    # perl -n -e 'if (m/2147483648/) { @data = split /[\s\/]+/, $_; print $data[-1]."\n"; }' /tmp/big_files > /tmp/big.ids  # noqa
    if options.big_ids:
        big = []
        f = open(options.big_ids, "r")
        for line in f:
            big.append(rlong(line))
        f.close()
        if not big:
            raise Exception("No valid IDs for truncated files!")

        filesQuery = "select owner.id, sum(origFile.size) as usage, " \
            "count(origFile.id) as total from " \
            "OriginalFile as origFile " \
            "join origFile.details.owner as owner " \
            "where origFile.id in (:big)"

        params = omero.sys.ParametersI()
        params.add('big', rlist(big))
        if options.ids:
            filesQuery += " and owner.id in (:ids) "
            params.add('ids', ids)

        filesQuery += "group by owner.id"

        result = queryService.projection(filesQuery, params, ctx)
        for row in result:
            oid = row[0]._val
            p_size = row[1]._val
            p_missing = row[2]._val * 2147483648
            p_truncated = p_size - p_missing
            if p_truncated < 0:
                raise Exception(
                    "Invalid size for amount of truncation: %d (%s)" %
                    (convert(p_truncated, 1), exps[oid][0]))
            usage_map[oid] = usage_map.get(oid, 0) - p_truncated
            if options.verbosity:
                print("%s : %s : Truncated Files %s (%s)" % (
                    oid, exps[oid][0],
                    locale.format('%d', p_truncated, True),
                    convert(p_truncated, 1)))

    # Convert to a list to allow sorting
    usage_list = []
    for (oid, p_size) in iter(usage_map.items()):
        dic = dict()
        dic['data'] = p_size
        dic['id'] = oid
        dic['label'] = exps[oid][0]
        dic['group'] = exps[oid][1]
        usage_list.append(dic)

    return sorted(usage_list, key=lambda k: k['data'], reverse=True)


def keyWidth(usage_list, key):
    width = 0
    for dic in usage_list:
        width = max(len(str(dic[key])), width)
    return width


def generate_group_list(usage_list, quota, options):
    group_list = []

    if quota:
        user_totals = {}
        for dic in usage_list:
            user_totals[dic['id']] = dic['data']

        group_map = {}
        for gid, dic in quota.items():
            t = 0
            group = {}
            group['id'] = 1
            group['label'] = gid.capitalize()
            for oid in dic['users']:
                if oid in user_totals:
                    t = t + user_totals.pop(oid, 0)
                    group_map[oid] = group['label']
            group['data'] = t
            # Only add if the group has some usage
            if t:
                if dic['size']:
                    # print("Calculating 100.0 * %d / %d" % (t, dic['size']))
                    group['quota'] = (100.0 * t) / dic['size']
                else:
                    group['quota'] = 0
                group_list.append(group)

        # All remaining users are placed in the unknown group
        t = 0
        group = {}
        group['id'] = 1
        group['label'] = 'Unknown'
        for oid, size in user_totals.items():
            t = t + size
            group_map[oid] = group['label']
        group['data'] = t
        group['quota'] = 0
        if t:
            group_list.append(group)

        # Re-map users to their quota groups
        if options.group:
            for dic in usage_list:
                dic['group'] = group_map.get(dic['id'])

    return sorted(group_list, key=lambda k: k['data'], reverse=True)


def add_host_details(conn, report):
    report.append("")
    report.append("Server: %s" % conn.host)
    report.append("Free space: %s" % convert(conn.getFreeSpace()))


def generateReport(usage_list, group_list, title, options, previous=None):
    (report, total) = generateUserReport(usage_list, title, options,
                                         previous)

    # Add quotas
    if group_list:
        group_report = generateGroupReport(group_list, title, options,
                                           previous)

        report.append("")
        report.extend(group_report)

    return (report, total)


def generateUserReport(usage_list, title, options, previous=None):
    if options.group:
        # Determine longest name from the 'name - group' labels
        width = 0
        for dic in usage_list:
            match = re.match("^(.*)\s+-", dic['label'])
            if match:
                width = max(len(match.group(1)), width)
            else:
                width = max(len(dic['label']), width)

        stringFormat = "%%-%ds - %%s" % width
        for dic in usage_list:
            data = dic['label'].split(' - ')
            dic['label'] = stringFormat % (data[0], data[1])

    total = 0
    for dic in usage_list:
        total += dic['data']

    stringFormat = "%%%ds %s %%-%ds %s %%%ds %s %%s" % (
        keyWidth(usage_list, 'id') + 1,
        options.delimiter,
        max(keyWidth(usage_list, 'label'), 5),  # 5 == len('Total')
        options.delimiter,
        len(locale.format('%d', total, True)),
        options.delimiter
        )

    report = []
    delta = ''
    if previous:
        date = "Now = %s" % time.strftime(DATE_FORMAT)
        prev = "Then = %s" % previous.strftime(DATE_FORMAT)
        d = datetime.now() - previous
        delta = "Delta = %s" % (timedelta(d.days, d.seconds))
    else:
        date = time.strftime(DATE_FORMAT)
        prev = ''
        delta = ''
    len_title = max(len(title), len(date), len(prev), len(delta))

    report.append("=" * len_title)
    report.append(title)
    report.append(date)
    if previous:
        report.append(prev)
        report.append(delta)
    report.append("=" * len_title)
    header = stringFormat % ("Id", "User", "Bytes", "Usage")
    report.append(header)
    report.append("-" * len(header))

    for dic in usage_list:
        report.append(stringFormat % (dic['id'], dic['label'],
                      locale.format('%d', dic['data'], True),
                      convert(dic['data'])))

    report.append("-" * len(header))
    report.append(stringFormat % ('', 'Total',
                  locale.format('%d', total, True), convert(total)))

    return (report, total)


def generateGroupReport(usage_list, title, options, previous=None):
    width_quota = len("Quota (%)")
    width_data = 0
    for dic in usage_list:
        width_data = max(len(locale.format('%d', dic['data'], True)),
                         width_data)
        width_quota = max(len("%.2f" % dic['quota']), width_quota)

    stringFormat = "%%-%ds %s %%-%ds %s %%%ds %s %%s" % (
        keyWidth(usage_list, 'label') + 1,
        options.delimiter,
        width_data,
        options.delimiter,
        width_quota,
        options.delimiter
        )

    report = []
    delta = ''
    if previous:
        date = "Now = %s" % time.strftime(DATE_FORMAT)
        prev = "Then = %s" % previous.strftime(DATE_FORMAT)
        d = datetime.now() - previous
        delta = "Delta = %s" % (timedelta(d.days, d.seconds))
    else:
        date = time.strftime(DATE_FORMAT)
        prev = ''
        delta = ''
    len_title = max(len(title), len(date), len(prev), len(delta))

    report.append("=" * len_title)
    report.append(title + " Group Report")
    report.append(date)
    if previous:
        report.append(prev)
        report.append(delta)
    report.append("=" * len_title)
    header = stringFormat % ("Group", "Bytes", "Quota (%)", "Usage")
    report.append(header)
    report.append("-" * len(header))

    for dic in usage_list:
        report.append(stringFormat % (dic['label'],
                      locale.format('%d', dic['data'], True),
                      "%.2f" % dic['quota'],
                      convert(dic['data'])))

    return report


def generateExcelReport(usage_list, group_list, title, options, previous=None):
    (report, total) = generateExcelUserReport(usage_list, title, options,
                                              previous)

    # Add quotas
    if group_list:
        group_report = generateExcelGroupReport(group_list, title, options,
                                                previous)
        report.append("")
        report.extend(group_report)

    return (report, total)


def generateExcelUserReport(usage_list, title, options, previous=None):
    report = []
    report.append(title)

    if previous:
        report.append('"Now = %s"' % time.strftime(DATE_FORMAT))
        report.append('"Then = %s"' % previous.strftime(DATE_FORMAT))
        d = datetime.now() - previous
        report.append('"Delta = %s"' % (timedelta(d.days, d.seconds)))
    else:
        report.append('"%s"' % time.strftime(DATE_FORMAT))

    if options.group:
        stringFormat = '"%s"\t"%s"\t%s\t"%s"'
        header = stringFormat % ("User", "Group", "Bytes", "Usage")
    else:
        stringFormat = '"%s"\t%s\t"%s"'
        header = stringFormat % ("User", "Bytes", "Usage")
    report.append(header)
    total = 0

    for dic in usage_list:
        total += dic['data']
        if options.group:
            (user, group) = dic['label'].split(' - ')
            report.append(stringFormat % (user.rstrip(), group, dic['data'],
                          convert(dic['data'])))
        else:
            report.append(stringFormat % (dic['label'], dic['data'],
                          convert(dic['data'])))

    if options.group:
        report.append(stringFormat % ('Total', '', total, convert(total)))
    else:
        report.append(stringFormat % ('Total', total, convert(total)))
    return (report, total)


def generateExcelGroupReport(usage_list, title, options, previous=None):
    report = []
    report.append(title + " Group Report")

    if previous:
        report.append('"Now = %s"' % time.strftime(DATE_FORMAT))
        report.append('"Then = %s"' % previous.strftime(DATE_FORMAT))
        d = datetime.now() - previous
        report.append('"Delta = %s"' % (timedelta(d.days, d.seconds)))
    else:
        report.append('"%s"' % time.strftime(DATE_FORMAT))

    stringFormat = '"%s"\t%s\t%s\t"%s"'
    header = stringFormat % ("Group", "Bytes", "Quota (%)", "Usage")
    report.append(header)

    for dic in usage_list:
        report.append(stringFormat % (dic['label'], dic['data'], dic['quota'],
                      convert(dic['data'])))

    return report


# Gather our code in a main() function
def main():
    parser = init_options()
    (options, args) = parser.parse_args()

    if options.quota_example:
        print("""# OMERO Quota File"
#
# Lines starting with # are comments.
# The file has a [Group] section followed by a [User] section.
# Users can be in only one group.
# A user not in a recognised group will be put into the 'unknown' group.
# Spaces are removed and names are case-insensitive.
#
[Group List]
# [Group] : [Quota]
Admin : 30gb
#
[User List]
# [OMERO User ID] : (Ignored Name Field) : [Group]
  2 : Alex  : Admin
 52 : Tom   : Tony""")
        sys.exit()

    if not args:
        parser.print_help()
        sys.exit(0)

    conn = None
    try:
        for userEmail in args:
            if not re.match("^[a-zA-Z0-9._%-]+@[a-zA-Z0-9._%-]+."
                            "[a-zA-Z]{2,6}$", userEmail):
                raise Exception("Invalid e-mail address: '%s'" % userEmail)

        if options.silent:
            if not args:
                raise Exception("No e-mail address for silent mode")
            # Turn off print messages
            options.debug = False
            options.verbosity = 0

        if options.debug:
            print("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        if options.debug:
            print("Connecting to OMERO ...")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        # Read group quotas
        quota = read_quota_file(options)
        if options.only_quota:
            ids = []
            for gid, dic in quota.items():
                ids.extend(dic['users'])
            options.ids = ",".join([str(x) for x in ids])

        usage_list = users_data(conn, options)

        previous = dict()
        if options.report:
            # Read previous usage
            try:
                f = open(options.report, "r")
                previous_date = datetime.fromtimestamp(
                    float(f.readline().rstrip()))
                for line in f:
                    data = line.split(',')
                    oid = int(data[0])
                    label = data[1]
                    p_size = int(data[2])
                    dic = dict()
                    dic['id'] = oid
                    dic['label'] = label
                    dic['data'] = p_size
                    previous[oid] = dic
                f.close()
            except Exception as e:
                # print(e)
                previous = None

            # Record current usage
            try:
                f = open(options.report, "w")
                f.write("%s\n" % time.time())
                for dic in usage_list:
                    f.write("%s,%s,%s\n" % (
                        dic['id'], dic['label'], dic['data']))
                f.close()
            finally:
                pass

        group_list = generate_group_list(usage_list, quota, options)

        # Add the group to the experimenter name.
        # Used for legacy processing with label only field.
        if options.group:
            for dic in usage_list:
                dic['label'] = "%s - %s" % (dic['label'], dic['group'])

        # Archive current usage
        if options.dir:
            name = os.path.join(options.dir, time.strftime(FILENAME_FORMAT))

            try:
                f = open(name, "w")
                f.write("%s\n" % time.time())
                for dic in usage_list:
                    f.write("%s,%s,%s\n" % (
                        dic['id'], dic['label'], dic['data']))
                f.close()
            finally:
                pass

        (report, total) = generateReport(usage_list, group_list,
                                         options.title, options)

        excel_report = []
        if args:
            (excel_report, total) = generateExcelReport(usage_list, group_list,
                                                        options.title, options)

        if (previous):
            # Create an incremental report using the previous usage
            new_usage_list = []
            # Remove previous usage from current
            for dic in usage_list:
                oid = dic['id']
                if oid in previous:
                    dic['data'] -= previous[oid]['data']
                    del previous[oid]

                if dic['data']:
                    new_usage_list.append(dic)

            # Any entries remaining are experimenters that are not in the
            # current list (i.e. have been removed from OMERO)
            for oid, dic in previous.items():
                dic['data'] = -dic['data']
                new_usage_list.append(dic)

            new_usage_list = sorted(new_usage_list, key=lambda k: k['data'],
                                    reverse=True)

            group_list = generate_group_list(new_usage_list, quota, options)

            (new_report, new_total) = generateReport(
                new_usage_list, group_list, "Incremental Usage", options,
                previous=previous_date)
            if new_total:
                report.append('')
                report.extend(new_report)

                if args:
                    (new_report, new_total) = generateExcelReport(
                        new_usage_list, group_list, "Incremental Usage",
                        options, previous=previous_date)
                    excel_report.append('')
                    excel_report.extend(new_report)

        # Summarise in a single string
        add_host_details(conn, report)

        report = "\n".join(report)
        if not options.silent:
            print(report)

        if excel_report:
            add_host_details(conn, excel_report)
            excel_report = "\n".join(excel_report)

        # E-mail the report to the specified e-mail addresses
        send_email(gdsc.omero.ADMIN_EMAIL, args,
                   "[%s] %s" % (options.title, convert(total, 2)),
                   report, excel_report)

    except Exception as e:
        print("ERROR: %s" % e)
    finally:
        if conn:
            conn.close()


# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
