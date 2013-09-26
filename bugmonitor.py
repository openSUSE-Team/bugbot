import argparse
from datetime import datetime
import re
import sqlite3

from imapclient import IMAPClient

try:
    import suse.bugzilla
except ImportError, e:
    print """*** please git clone git://bolzano/suse/solid-ground
*** then symlink the suse subdir here"""
    raise


# IMAP parameters
IMAP_HOST     = 'imap.gmail.com'
IMAP_USERNAME = ''
IMAP_PASSWORD = ''

# Bugzilla parameters
BZ_HOST     = 'https://apibugzilla.novell.com'
BZ_USERNAME = ''
BZ_PASSWORD = ''

# IRC Parameters
IRC_HOST    = 'irc.freenode.org'
IRC_NICK    = 'Furcifer'
IRC_CHANNEL = '#opensuse-pizza-hackaton'

START = datetime(2013, 9, 27)
STOP  = datetime(2013, 9, 28)

DBNAME = 'bugmonitor.db'

# Points table
TABLE = {
    'FIX GOLD':  100,
    'FIX SILVER': 80,
    'FIX BRONZE': 60,
    'FIX OTHER':  50,
    'SCR GOLD':   25,
    'SCR SILVER': 20,
    'SCR BRONZE': 15,
    'SCR OTHER':  10,
}

HTML = '/tmp/table.html'

def initdb(dbname):
    """Initialize the database, removing old data."""
    conn = sqlite3.connect(dbname)
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS timeline')
    c.execute("""CREATE TABLE timeline (
                     date DATETIME,
                     name TEXT,
                     assigned_to TEXT,
                     changed_fields TEXT,
                     classification TEXT,
                     component TEXT,
                     foundby TEXT,
                     keywords TEXT,
                     priority TEXT,
                     product TEXT,
                     severity TEXT,
                     status TEXT,
                     target_milestone TEXT,
                     type TEXT,
                     version TEXT,
                     who TEXT,
                     body TEXT)""")

    c.execute('DROP TABLE IF EXISTS ranking')
    c.execute("""CREATE TABLE ranking (
                     name TEXT,
                     gold_fix INTEGER,
                     silver_fix INTEGER,
                     bronze_fix INTEGER,
                     other_fix INTEGER,
                     gold_scr INTEGER,
                     silver_scr INTEGER,
                     bronze_scr INTEGER,
                     other_scr INTEGER,
                     suspicious INTEGER,
                     other INTEGER)""")

    c.execute('DROP INDEX IF EXISTS ranking_name_idx')
    c.execute('CREATE UNIQUE INDEX ranking_name_idx ON ranking (name)')

    c.execute('DROP TABLE IF EXISTS ranking_log')
    c.execute("""CREATE TABLE ranking_log (
                     name TEXT,
                     bugid TEXT,
                     status TEXT)""")

    conn.commit()
    conn.close()


def login(host, user, passwd, ssl):
    """Connect to an IMAP server.

    Arguments:
        host   -- server hostname
        user   -- username for the connection
        passwd -- account password
        ssl    -- use SSL connection protocol

    Returns:
        IMAPClient instance

    """
    server = IMAPClient(host, use_uid=False, ssl=ssl)
    server.login(user, passwd)
    return server


def process_msg(msg):
    """Convert a single message into a bug action.

    Arguments:
        msg -- message fetched from the server

    Returns:
        A dictionary object that represent a bug action

    """
    date_ = msg['INTERNALDATE']
    name = msg['ENVELOPE'][1]

    headers = msg['BODY[HEADER]']
    xbug = dict()
    for line in headers.split('\r\n'):
        if line.startswith('X-Bugzilla'):
            i = line.index(':')
            k, v = line[:i], line[i+1:]
            xbug[k] = v.strip()

    body = msg['BODY[TEXT]']

    return {
        'date': date_,
        'name': name,
        'assigned-to': xbug['X-Bugzilla-Assigned-To'],
        'changed-fields': xbug['X-Bugzilla-Changed-Fields'],
        'classification': xbug['X-Bugzilla-Classification'],
        'component': xbug['X-Bugzilla-Component'],
        'foundby': xbug['X-Bugzilla-Foundby'],
        'keywords': xbug['X-Bugzilla-Keywords'],
        'priority': xbug['X-Bugzilla-Priority'],
        'product': xbug['X-Bugzilla-Product'],
        'severity': xbug['X-Bugzilla-Severity'],
        'status': xbug['X-Bugzilla-Status'],
        'target-milestone': xbug['X-Bugzilla-Target-Milestone'],
        'type': xbug['X-Bugzilla-Type'],
        'version': xbug['X-Bugzilla-Version'],
        'who': xbug['X-Bugzilla-Who'],
        'body': body,
    }


def store(dbname, bug):
    """Store a single bug action.

    Arguments:
        dbname -- database name
        bug    -- a dict that store a bug action

    """
    conn = sqlite3.connect(dbname)
    c = conn.cursor()
    c.execute("""INSERT INTO timeline
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
              (bug['date'],
               bug['name'],
               bug['assigned-to'],
               bug['changed-fields'],
               bug['classification'],
               bug['component'],
               bug['foundby'],
               bug['keywords'],
               bug['priority'],
               bug['product'],
               bug['severity'],
               bug['status'],
               bug['target-milestone'],
               bug['type'],
               bug['version'],
               bug['who'],
               bug['body']))
    conn.commit()
    conn.close()


_cache = {}
def get_bug_evaluation(bugid):
    """Get bug evaluation. Use an external cache for external invalidation"""

    if bugid in _cache:
        return _cache[bugid]

    bz = suse.bugzilla.Bugzilla(None, None, base=BZ_HOST)
    bz.browser.add_password(BZ_HOST, BZ_USERNAME, BZ_PASSWORD)
    bug = bz.get_bugs(ids=(bugid,))[0]

    evaluation = None
    if hasattr(bug, 'status_whiteboard'):
        for evaluation in ('GOLD', 'SILVER', 'BRONZE'):
            if evaluation in bug.status_whiteboard:
                break

    _cache[bugid] = evaluation

    return evaluation


def is_fix(bug):
    return (bug['type'] == 'changed' and
            'Status' in bug['changed-fields'] and
            'Resolution' in bug['changed-fields'] and
            bug['status'] in ('CLOSED', 'RESOLVED')) 


def is_scr(bug):
    return (bug['type'] == 'changed' and
            bug['status'] not in ('CLOSED', 'RESOLVED') and
            '--- Comment #' in bug['body'] and
            'This is an autogenerated message for OBS integration' not in bug['body'])


def is_new(bug):
    return bug['type'] == 'new'


def is_reopen(bug):
    return (bug['type'] == 'changed' and
            'Status' in bug['changed-fields'] and
            bug['status'] not in ('CLOSED', 'RESOLVED') and
            re.search(r'Status|\s*CLOSED\s*|', bug['body']))


def is_auto(bug):
    return ('--- Comment #' in bug['body'] and
            'This is an autogenerated message for OBS integration' in bug['body'])


def is_suspicious(bug):
    return (bug['type'] == 'changed' and
            'Whiteboard' in bug['changed-fields'])


def evaluate(dbname, bug):
    """Evaluate a bug action. Update the ranking table.

    Arguments:
        dbname -- database name
        bug    -- a dict that store a bug action

    """

    conn = sqlite3.connect(dbname)
    c = conn.cursor()

    c.execute('SELECT * FROM ranking WHERE name=?', (bug['who'],))
    row = c.fetchone()
    (_, gold_fix, silver_fix, bronze_fix, other_fix,
     gold_scr, silver_scr, bronze_scr, other_scr,
     suspicious, other) = row if row else [0]*11

    bugid = re.findall(r'\[Bug (\d+)\].*', bug['name'])[0]
    evaluation = get_bug_evaluation(bugid)

    status = [evaluation if evaluation else 'Other']

    if is_fix(bug):
        status.append('FIX')
        if evaluation == 'GOLD':
            gold_fix += 1
        elif evaluation == 'SILVER':
            silver_fix += 1
        elif evaluation == 'BRONZE':
            bronze_fix += 1
        else:
            other_fix += 1
    elif (is_scr(bug) or is_new(bug)) and not is_auto(bug):
        status.append('SCR/NEW')
        if evaluation == 'GOLD':
            gold_scr += 1
        elif evaluation == 'SILVER':
            silver_scr += 1
        elif evaluation == 'BRONZE':
            bronze_scr += 1
        else:
            other_scr += 1
    elif is_suspicious(bug) or is_reopen(bug):
        status.append('SUSPICIOUS/REOPEN')
        suspicious += 1
    else:
        status.append('OTHER')
        other += 1

    print (bug['who'], gold_fix, silver_fix, bronze_fix, other_fix,
           gold_scr, silver_scr, bronze_scr, other_scr, suspicious, other)
    print (bug['who'], bugid, ','.join(status))

    if row:
        c.execute("""UPDATE ranking
                     SET gold_fix=?,
                         silver_fix=?,
                         bronze_fix=?,
                         other_fix=?,
                         gold_scr=?,
                         silver_scr=?,
                         bronze_scr=?,
                         other_scr=?,
                         suspicious=?,
                         other=?
                     WHERE name=?""", 
                  (gold_fix,
                   silver_fix,
                   bronze_fix,
                   other_fix,
                   gold_scr,
                   silver_scr,
                   bronze_scr,
                   other_scr,
                   suspicious,
                   other,
                   bug['who']))
    else:
        c.execute("""INSERT INTO ranking
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                  (bug['who'],
                   gold_fix,
                   silver_fix,
                   bronze_fix,
                   other_fix,
                   gold_scr,
                   silver_scr,
                   bronze_scr,
                   other_scr,
                   suspicious,
                   other))

    c.execute("""INSERT INTO ranking_log
                 VALUES (?, ?, ?)""", 
              (bug['who'],
               bugid,
               ','.join(status)))

    conn.commit()
    conn.close()


def process(dbname, msgids):
    messages = srv.fetch(msgids, ('FLAGS', 'INTERNALDATE', 'ENVELOPE',
                                  'BODY[HEADER]', 'BODY[TEXT]'))
    print 'Processing %d unread messages...' % len(messages)
    for msgid, msg in messages.iteritems():
        try:
            bug = process_msg(msg)
        except:
            print 'Error processing the bug email [%s]'%msg['ENVELOPE'][1]
            continue

        store(dbname, bug)
        # if START <= bug['date'] < STOP:
        #     evaluate(dbname, bug)
        evaluate(dbname, bug)


def ranking(dbname, html=False):
    conn = sqlite3.connect(dbname)
    c = conn.cursor()
    c.execute('SELECT * FROM ranking')

    table = []
    for row in c:
        table.append(list(row))
        l = table[-1]
        points = (l[1] * TABLE['FIX GOLD'] +
                  l[2] * TABLE['FIX SILVER'] +
                  l[3] * TABLE['FIX BRONZE'] +
                  l[4] * TABLE['FIX OTHER'] +
                  l[5] * TABLE['SCR GOLD'] +
                  l[6] * TABLE['SCR SILVER'] +
                  l[7] * TABLE['SCR BRONZE'] +
                  l[8] * TABLE['SCR OTHER'])
        l.append(points)

    conn.close()
    table.sort(key=lambda x: x[-1], reverse=True)

    if not html:
        return table

    table_html = """<!DOCTYPE HTML>
<html lang = "en">
  <head>
    <title>Beta Pizza Hackathon Ranking</title>
    <meta charset="UTF-8" />
    <meta http-equiv="Cache-control" content="no-cache">
    <meta http-equiv="refresh" content="300" />
    <style type = "text/css">
    table, td, th {
      border: 1px solid black;
    } 
    </style>
  </head>
  <body>
    <h1>Ranking</h1>
    <table>
      <tr>
        <th>User</th>
        <th>Fix Gold</th>
        <th>Fix Silver</th>
        <th>Fix Bronze</th>
        <th>Fix Other</th>
        <th>Scr Gold</th>
        <th>Scr Silver</th>
        <th>Scr Bronze</th>
        <th>Scr Other</th>
        <th>Suspicious</th>
        <th>Other</th>
        <th>Total</th>
      </tr>"""
    for line in table:
        table_html += '\n<tr>' + ''.join('<td>%s</td>'%v for v in line) + '</tr>'
    table_html += """
    </table>
  </body>
</html>"""
    return table_html


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monitor an IMAP account for BNC emails.')
    parser.add_argument('-i', '--initdb', action='store_true',
                        help='initialize the database (CAUTION)')
    parser.add_argument('-d', '--db', default=DBNAME, help='database name')
    parser.add_argument('--imap-host', default=IMAP_HOST, help='IMAP server')
    parser.add_argument('--imap-user', default=IMAP_USERNAME, help='IMAP user name')
    parser.add_argument('--imap-password', default=IMAP_PASSWORD, help='IMAP password')
    parser.add_argument('-s', '--ssl', action='store_true',
                        help='utilize SSL protocol in IMAP connection')
    parser.add_argument('--bz-host', default=BZ_HOST, help='bugzilla server')
    parser.add_argument('--bz-user', default=BZ_USERNAME, help='bugzilla user name')
    parser.add_argument('--bz-password', default=BZ_PASSWORD, help='bugzilla password')
    parser.add_argument('--irc-host', default=IRC_HOST, help='IRC server')
    parser.add_argument('--nick', default=IRC_NICK, help='IRC nick name')
    parser.add_argument('--channel', default=IRC_CHANNEL, help='IRC channel')

    args = parser.parse_args()

    dbname = args.db
    ssl = args.ssl if 'gmail' not in args.imap_host else True

    if args.initdb:
        print 'Reseting the database.'''
        initdb(dbname)

    srv = login(args.imap_host, args.imap_user, args.imap_password, ssl)
    srv.select_folder('INBOX')

    # Process all the unread messages
    criteria = (
        'NOT DELETED', 
        'UNSEEN',
        'FROM bugzilla_noreply@novell.com',
    )
    process(dbname, srv.search(criteria))
    with open(HTML, 'w') as f:
        print >>f, ranking(dbname, html=True)

    print 'Processing new messages to arrive...'
    while True:
        srv.idle()
        response = srv.idle_check()
        srv.idle_done()
        process(dbname, [r[0] for r in response if r[1] == 'EXISTS'])
        with open(HTML, 'w') as f:
            print >>f, ranking(dbname, html=True)

    srv.idle_done()
