import argparse
import configparser
from datetime import datetime
try:
    import grp, pwd
except ModuleNotFoundError:
    pass
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
import sys
import zlib
argparser = argparse.ArgumentParser(description='A simple implementation of git')
argsubparser = argparser.add_subparsers(dest='command', required=True, title='Commands', description='Available commands')

class GitRepo(object):
    """A git repository"""
    worktree = None
    gitdir = None
    conf = None
    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, '.git')
        if not (force or os.path.isdir(self.gitdir)):
            raise Exception(f'{path} is not a Git repository')
        
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, 'config')
        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception('Configuration file missing')
        
        if not force:
            vers = int(self.conf.get('core', 'repositoryformatversion'))
            if vers != 0:
                raise Exception(f'Unsupported repositoryformatversion {vers}')
    
def repo_path(repo, *path):
    """Compute path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)

def repo_dir(repo, *path, mkdir=False):
    path = repo_path(repo, *path)
    if os.path.exists(path):
        if os.path.isdir(path):
            return path
        else:
            raise Exception(f'{path} is not a directory')
    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None
    
def repo_file(repo, *path, mkdir=False):
    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)
    
def repo_create(path):
    """Create a new repository at path"""
    repo = GitRepo(path, force=True)
    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception(f'{path} is not a directory')
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception(f'{path} is not empty')
    else:
        os.makedirs(repo.worktree)
    
    assert repo_dir(repo, 'branches', mkdir=True)
    assert repo_dir(repo, 'objects', mkdir=True)
    assert repo_dir(repo, 'refs', 'tags', mkdir=True)
    assert repo_dir(repo, 'refs', 'heads', mkdir=True)

    with open(repo_file(repo, "description"), 'w') as f:
        f.write("Edit this file desc to name the repository\n")
    with open(repo_file(repo, "HEAD"), 'w') as f:
        f.write("ref: ref/heads/masters\n")

    with open(repo_file(repo, "config"), 'w') as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    conf = configparser.ConfigParser()
    conf.add_section("core")
    conf.set("core", "repositoryformatversion", "0")
    conf.set("core", "filemode", "false")
    conf.set("core", "bare", "false")
    return conf

argsp = argsubparser.add_parser("init", help="Initialize a new empty repo")
argsp.add_argument("path", metavar="directory", nargs="?", default=".", help="Where to create the repo")

def git_init(args):
    repo_create(args.path)
  
def repo_find(path = '.', required = True):
    path = os.path.realpath(path)
    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepo(path)
    
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        if required:
            raise Exception("No git directory")
        else:
            return None
        
    return repo_find(parent, required)

class GitObject (object):
    def __init__(self, data = None):
        if data!=None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self, repo):
        raise Exception("Not implemented")
    def deserialize(self, data):
        raise Exception("Not implemented")
    
    def init(self):
        pass

def object_read(repo, sha):
    path = repo_file(repo, "objects", sha[0:2], sha[2:])
    if not os.path.isfile(path):
        return None
    
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        x = raw.find(b' ')
        fmt = raw[:x]
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception(f"malformed object {sha}: bad length")
        
        match fmt:
            case b'commit': c = GitCommit
            case b'tree': c = GitTree
            case b'tag': c = GitTag
            case b'blob': c = GitBlob
            case _:
                raise Exception(f"Unknown type {fmt.decode('ascii')} for object {sha}")
            
        return c(raw[y+1:])
    
def object_write(obj, repo = None):
    data = obj.serialize()
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data
    sha = hashlib.sha1(result).hexdigest()
    if repo:
        path = repo_file(repo, "object", sha[0:2], sha[2:], mkdir=True)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(zlib.compress(result))
    return sha

class GitBlob(GitObject):
    fmt = b'blob'
    def serialize(self):
        return self.blobdata
    def deserialize(self, data):
        self.blobdata = data

argsp = argsubparser.add_parser("cat-file", help="Provide content of repository object")
argsp.add_argument("type",metavar="type",choices=["blob", "commit", "tag", "tree"], help="Specify the type")
argsp.add_argument("object", metavar="object", help="the object to display")

def object_find(repo, name, fmt = None, follow = True):
    return name

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

def git_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt = args.type.encode())

argsp = argsubparser.add_parser("hash-object", help="Compute object id and optionally creates a blob from a file")
argsp.add_argument("-t", metavar="type", dest="type", choices=["blob", "commit", "tag", "tree"], default="blob",
                   help="Specify the type")

argsp.add_argument("-w", dest="write", action="store_true", help="Actually write the object into the database")
argsp.add_argument("path", help="Read object from file")

def object_hash(f, fmt, repo = None):
    data = f.read()
    match fmt:
        case b'commit': obj = GitCommit(data)
        case b'tree': obj = GitTree(data)
        case b'tag': obj = GitTag(data)
        case b'blob': obj = GitBlob(data)
        case _: raise Exception(f"Unknown type {fmt}")

    return object_write(obj, repo)

def git_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None
    with open(args.path, "rb") as f:
        sha = object_hash(f, args.type.encode(), repo)
        print(sha)

def main(argv = sys.argv[1:]):
    args=argparser.parse_args(argv)
    match args.command:
        case 'init': git_init(args)
        case 'add': git_add(args)
        case 'commit': git_commit(args)
        case 'log': git_log(args)
        case 'status': git_status(args)
        case 'checkout': git_checkout(args)
        case 'branch': git_branch(args)
        case 'cat-file': git_cat_file(args)
        case 'check-ignore': git_check_ignore(args)
        case 'ls-files': git_ls_files(args)
        case 'checkout': git_checkout(args)
        case 'hash-object': git_hash_object(args)
        case 'rev-parse': git_rev_parse(args)
        case 'tag': git_tag(args)
        case 'ls-tree': git_ls_tree(args)
        case 'rm': git_rm(args)
        case 'show-ref': git_show_ref(args)
        case 'tag': git_tag(args)
        case _: print(f'Unknown command: {args.command}')


    