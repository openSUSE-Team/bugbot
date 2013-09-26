import argparse
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


DBNAME = 'bugmonitor.db'

# Evaluation constants
NONE   = 0
GOLD   = 1
SILVER = 2
BRONZE = 3


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
    (gold_fix, silver_fix, bronze_fix, other_fix,
     gold_scr, silver_scr, bronze_scr, other_scr,
     suspicious, other) = row if row else [0]*10

    bugid = re.findall(r'\[Bug (\d+)\].*', bug['name'])[0]
    evaluation = get_bug_evaluation(bugid)

    status = [evaluation]

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

    print (bug['who'],
                   gold_fix,
                   silver_fix,
                   bronze_fix,
                   other_fix,
                   gold_scr,
                   silver_scr,
                   bronze_scr,
                   other_scr,
                   suspicious,
                   other)
    print (bug['who'],
               bugid,
               ','.join(status))

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


def process(msgids):
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
        evaluate(dbname, bug)


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
    process((329,)) # srv.search(criteria))

    print 'Processing new messages to arrive...'
    while True:
        srv.idle()
        response = srv.idle_check()
        srv.idle_done()
        process([r[0] for r in response if r[1] == 'EXISTS'])

    srv.idle_done()
