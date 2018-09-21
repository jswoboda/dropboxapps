#!python

from __future__ import print_function

import argparse
import contextlib
import datetime
import os
import six
import sys
import time
import unicodedata
import glob
import pdb
import dropbox
import fnmatch
def main():
    args = parse_command_line()

    folder = args.folder
    rootdir = os.path.expanduser(args.rootdir)
    print('Dropbox folder name:', folder)
    print('Local directory:', rootdir)
    if not os.path.exists(rootdir):
        print(rootdir, 'does not exist on your filesystem')
        sys.exit(1)
    elif not os.path.isdir(rootdir):
        print(rootdir, 'is not a folder on your filesystem')
        sys.exit(1)

    dbx = dropbox.Dropbox(args.token)
    ver = args.verbose

    dir_v, dir_real_name, r_v = list_folder(dbx, folder)
    dirlist = [os.path.relpath(dir_real_name[i], folder) for i in dir_real_name.keys()]
    dirlist2 = [os.path.join(rootdir, i) for i in dirlist]
    #locfiles = [os.path.split(i)[-1] for i in glob.glob(os.path.join(rootdir, '*'))]
    locfiles = []
    for root, dirnames, filenames in os.walk(rootdir):
        for filename in fnmatch.filter(filenames, '*'):
            fullname = os.path.join(root, filename)
            if os.path.isfile(fullname):
                locfiles.append(os.path.relpath(os.path.join(root, filename), rootdir))
    rv_files, dtwice = compfolders(r_v, locfiles, rootdir)
    fsizes = [r_v[i].size for i in rv_files]
    print('Downloading {0:d} files totalling {1}'.format(len(fsizes), size_arg(sum(fsizes))))
    print('Will also redownload {0:d} file(s)'.format(len(dtwice)))
    if yesno('Start file download?', False):
        makedirstructure(dirlist2)
        while rv_files:
            rv_files = compfolders(r_v, locfiles, rootdir)[0]
            fsizes = [r_v[i].size for i in rv_files]
            try:
                download_files(dbx, rv_files, folder, rootdir, fsizes, ver)
                break
            except dropbox.files.DownloadError:
                dbx = dropbox.Dropbox(args.token)
def makedirstructure(dirlist2):
    for i in dirlist2:
        if not os.path.exists(i):
            os.makedirs(i)
def compfolders(r_v, locfiles, local_path):
    rv_files = r_v.keys()
    interfiles = list(set(rv_files).intersection(set(locfiles)))
    dtwice = []
    for f_1 in interfiles:
        fsize = os.path.getsize(os.path.join(local_path, f_1))
        if fsize == r_v[f_1].size:
            rv_files.remove(f_1)
        else:
            dtwice.append(f_1)
    return rv_files, dtwice
def size_arg(numbytes):
    """ Makes Human readiable memory sizes"""
    str_temp = '{0:.2f} {1}'
    if numbytes < 2**10:
        outstr = str_temp.format(float(numbytes), 'B')
    elif numbytes < 2**20:
        outstr = str_temp.format(float(numbytes)*2**-10, 'kB')
    elif numbytes < 2**30:
        outstr = str_temp.format(float(numbytes)*2**-20, 'MB')
    elif numbytes < 2**40:
        outstr = str_temp.format(float(numbytes)*2**-30, 'GB')
    else:
        outstr = str_temp.format(float(numbytes)*2**-40, 'TB')
    return outstr
def time_arg(numsecs):
    """
        Makes a string of human readable time given the number of seconds.
    """
    if numsecs < 60:
        strout = '{:d} seconds'.format(int(numsecs))
    elif numsecs < 3600:
        nmins = int(numsecs/60)
        strout = '{:d} minutes'.format(nmins)
    else:
        nhours = int(numsecs/3600)
        nmins = int((numsecs%3600)/60)
        strout = '{:d} hours & {:d} minutes'.format(nhours, nmins)
    return strout

def list_folder(dbx, path):
    """List a folder.

    Return a dict mapping unicode filenames to
    FileMetadata|FolderMetadata entries.
    """
    try:
        with stopwatch('list_folder'):
            res = dbx.files_list_folder(path, recursive=True)
            if not res.has_more:
                r_list = [res]
            else:
                r_list = []
            while res.has_more:
                res = dbx.files_list_folder_continue(res.cursor)
                r_list.append(res)

    except dropbox.exceptions.ApiError as err:
        print('Folder listing failed for', path, '-- assumed empty:', err)
        return {}
    else:
        dir_v = {}
        r_v = {}
        dir_names = [path]
        dir_real_name = {path.lower():path}
        for res in r_list:
            for entry in res.entries:
                if type(entry) is dropbox.files.FolderMetadata:
                    p1 = os.path.split(entry.path_display)[0]
                    if not p1 in dir_names and p1.lower() in dir_real_name.keys():
                        rname = os.path.join(dir_real_name[p1.lower()], entry.name)
                        dir_real_name[entry.path_lower] = rname
                        dir_names.append(rname)
                    else:
                        dir_names.append(entry.path_display)
                        dir_real_name[entry.path_lower] = entry.path_display
                    dir_v[entry.path_lower] = entry

        for res in r_list:
            for entry in res.entries:
                if type(entry) is dropbox.files.FileMetadata:
                    p_1 = os.path.split(entry.path_lower)[0]
                    rel_path = os.path.relpath(dir_real_name[p_1], path)
                    if rel_path == '.':
                        rel_path = ''
                    p_name = os.path.join(rel_path, entry.name)
                    r_v[p_name] = entry
        del dir_real_name[path.lower()]
        return dir_v, dir_real_name, r_v

def download_files(dbx, rv_files, path, local_path, fsizes, ver=False):
    """
        Download files in a folder on dropbox to a local directory.

        Args:
            dbx (:obj:'dropbox'): An instance of the class that the Dropbox API
                                  uses for accessing the user's account.
            path (:obj:'str'): The path of the folder on the dropbox account.
            local_path (:obj:'str'): The path of the directory on the local machine.
            ver (:obj:'bool'): The verbose flag.
    """

    time_sum = 0

    st1 = 'Downloading file {0} of {1}, {2} remain. Name:{3}'
    for i_file, cur_file in enumerate(rv_files):
        dfile = os.path.join(path, cur_file)
        lfile = os.path.join(local_path, cur_file)
        rat_left = float(sum(fsizes))/(sum(fsizes[:i_file])+1e-15)-1
        time_str = time_arg(time_sum*rat_left)
        if ver:
            print(st1.format(i_file+1, len(rv_files), time_str, cur_file))
        t_0 = time.time()
        out1 = dbx.files_download_to_file(lfile, dfile)
        t_1 = time.time()
        time_sum += t_1-t_0
def parse_command_line(str_input=None):
    """
        This will parse through the command line arguments
    """
    # if str_input is None:
    parser = argparse.ArgumentParser()
    # else:
    #     parser = argparse.ArgumentParser(str_input)
    parser.add_argument("-v", "--verbose", action="store_true",
                        dest="verbose", default=False,
                        help="prints debug output and additional detail.")
    parser.add_argument('-f', '--folder', dest='folder', default='',
                        help='Path on Dropbox.')
    parser.add_argument('-d', '--rootdir', dest='rootdir', default='~/',
                        help='Path on local machine files will be saved to')
    parser.add_argument('-t', '--token', dest='token', default='',
                        help='Access token. '
                        '(see https://www.dropbox.com/developers/apps)')
    if str_input is None:
        return parser.parse_args()
    else:
        return parser.parse_args(str_input)

def yesno(message, default):
    """Handy helper function to ask a yes/no question.

    Command line arguments --yes or --no force the answer;
    --default to force the default answer.

    Otherwise a blank line returns the default, and answering
    y/yes or n/no returns True or False.

    Retry on unrecognized answer.

    Special answers:
    - q or quit exits the program
    - p or pdb invokes the debugger
    """

    if default:
        message += '? [Y/n] '
    else:
        message += '? [N/y] '
    while True:
        answer = raw_input(message).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False
        if answer in ('q', 'quit'):
            print('Exit')
            raise SystemExit(0)
        if answer in ('p', 'pdb'):
            import pdb
            pdb.set_trace()
        print('Please answer YES or NO.')
@contextlib.contextmanager
def stopwatch(message):
    """Context manager to print how long a block of code took."""
    t0 = time.time()
    try:
        yield
    finally:
        t1 = time.time()
        print('Total elapsed time for %s: %.3f' % (message, t1 - t0))

if __name__ == '__main__':
    main()
