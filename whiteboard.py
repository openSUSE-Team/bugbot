import argparse
import csv


try:
    import suse.bugzilla
except ImportError, e:
    print """*** please git clone git://bolzano/suse/solid-ground
*** then symlink the suse subdir here"""
    raise

URL = 'https://apibugzilla.novell.com'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import CSV bug evaluation into BNC.')
    parser.add_argument('cvsfile', metavar='FILE', type=str,
                        help='CVS file with the evaluation')
    args = parser.parse_args()

    bugs = {}

    with open(args.cvsfile) as f:
        reader = csv.reader(f)
        for row in reader:
            if row[0].isdigit():
                bugs[row[0]] = row[8]

    bz = suse.bugzilla.Bugzilla(None, None, base=URL)
    bz.browser.add_password(URL, 'X', 'X')
    all_bugs = bz.get_bugs(ids=bugs.keys())
    for bug in all_bugs:
        print bug.bug_id, '[%s]'%bug.status_whiteboard if hasattr(bug, 'status_whiteboard') else '--EMPTY--'

        if hasattr(bug, 'status_whiteboard') and \
           bugs[bug.bug_id] and \
           bugs[bug.bug_id] in bug.status_whiteboard:
            print 'CONTINUE'
            continue
        else:
            for i in ('GOLD', 'SILVER', 'BRONZE'):
                if hasattr(bug, 'status_whiteboard') and i in bug.status_whiteboard:
                    print 'REMOVE / UPDATE'
                    bz.update_bug(bug.bug_id, whiteboard_remove=i)
            if bugs[bug.bug_id]:
                print 'ADD'
                bz.update_bug(bug.bug_id, whiteboard_add=bugs[bug.bug_id])
