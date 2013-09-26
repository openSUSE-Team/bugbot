import argparse
import re
import sqlite3

from imapclient import IMAPClient


# IMAP parameters
HOST     = 'imap.gmail.com'
USERNAME = 'X'
PASSWORD = 'X'

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
                     gold_scr INTEGER,
                     silver_scr INTEGER,
                     bronze_scr INTEGER,
                     suspicious INTEGER,
                     other INTEGER)""")

    c.execute('DROP INDEX IF EXISTS ranking_name_idx')
    c.execute('CREATE UNIQUE INDEX ranking_name_idx ON ranking (name)')

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
    server = IMAPClient(host, use_uid=True, ssl=ssl)
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
    gold_fix, silver_fix, bronze_fix, gold_scr, silver_scr, bronze_scr, suspicious, other = row if row else [0]*8

    if row:
        c.execute("""UPDATE ranking
                     SET gold_fix=?,
                         silver_fix=?,
                         bronze_fix=?,
                         gold_scr=?,
                         silver_scr=?,
                         bronze_scr=?,
                         suspicious=?,
                         other=?
                     WHERE name=?""", 
                  (gold_fix,
                   silver_fix,
                   bronze_fix,
                   gold_scr,
                   silver_scr,
                   bronze_scr,
                   suspicious,
                   other,
                   bug['who']))
    else:
        c.execute("""INSERT INTO ranking
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                  (bug['who'],
                   gold_fix,
                   silver_fix,
                   bronze_fix,
                   gold_scr,
                   silver_scr,
                   bronze_scr,
                   suspicious,
                   other))

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
    parser.add_argument('-o', '--host', default=HOST, help='IMAP server')
    parser.add_argument('-u', '--user', default=USERNAME, help='user name')
    parser.add_argument('-p', '--password', default=PASSWORD, help='password')
    parser.add_argument('-s', '--ssl', action='store_true',
                        help='utilize SSL protocol')

    args = parser.parse_args()

    dbname = args.db
    host = args.host
    username = args.user
    password = args.password
    ssl = args.ssl if 'gmail' not in host else True

    if args.initdb:
        print 'Reseting the database.'''
        initdb(dbname)

    srv = login(host, username, password, ssl)
    srv.select_folder('INBOX')

    # Process all the unread messages
    criteria = (
        'NOT DELETED', 
        'UNSEEN',
        'FROM bugzilla_noreply@novell.com',
    )
    process((329,)) # srv.search(criteria))

    # Processing new messages to arrive
    srv.idle()
    print 'Processing new messages to arrive...'
    while True:
        response = srv.idle_check()
        process(msgid for msgid, r in response if r == 'EXISTS')

    srv.idle_done()
