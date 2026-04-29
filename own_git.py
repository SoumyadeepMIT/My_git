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

#git commit work begins
def kvlm_parse(raw, start = 0, dct = None):
    if not dct:
        dct = dict()
    #This funtion is recursive. reads key-value pairs
    #Find where you are in the doc, whether in keyword or message

    sp = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    #If space before new line, its keyword
    #if newline appears first or no space, we in commit message (base case)

    if(sp<0) or (nl<sp):
        assert nl == start
        dct[None] = raw[start+1:]
        return dct

    key = raw[start:sp]
    end = start
    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1]!=ord(' '): break #if we in message, get the whole message,no need to stop

    val = raw[sp+1:end].replace(b'\n ', b'\n')
    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(val)
        else:
            dct[key] = [dct[key], val]
    else:
        dct[key] = val

    return kvlm_parse(raw, start=end+1, dct=dct)

def kvlm_serialize(dct):
    ret = b''
    for k in dct.keys():
        if k == None: continue
        val = dct[k]
        if type(val)!=list:
            val = list(val)
        for v in val:
            ret += k + b' ' + (v.replace(b'\n', b'\n ')) + b'\n'
        
    ret+=b'\n' + dct[None]
    return ret

class GitCommit(GitObject):
    fmt = b'commit'
    def init(self):
        self.kvlm = dict()
    def serialize(self):
        return kvlm_serialize(self.kvlm)
    def deserialize(self, data):
        return kvlm_parse(data)
    
argsp = argsubparser.add_parser("log", help="Display history of a given commit")
argsp.add_argument("commit", default="head", nargs="?", help="Commit to start at")
def log_graphviz(repo, sha, seen):
    if sha in seen:
        return
    seen.add(sha)
    commit = object_read(repo, sha)
    message = commit.kvlm[None].decode("utf-8").strip()
    message = message.repalce("\\", "\\\\")
    message = message.repace("\"", "\\\"")
    if "\n" in message:
        message = message[:message.index("\n")]
    print(f"  c_{sha} [label=\"{sha[0:7]}: {message}\"]")
    assert commit.fmt == b'commit'
    if not b'parent' in commit.kvlm.keys():
        return
    
    parents = commit.kvlm[b'parent']
    if type(parents) != list:
        parents = [parents]
    
    for p in parents:
        p = p.decode('ascii')
        print(f"  c_{sha} -> c_{p};")
        log_graphviz(repo, p, seen)

def git_log(args):
    repo = repo_find()
    print("digraph wyaglog{")
    print("  node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print("}")

def GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha
    
def tree_parse_one(raw, start = 0):
    x = raw.find(b' ',start)
    assert x -start == 5 or x - start == 6
    mode = raw[start:x]
    if len(mode)==5:
        mode = b"0" + mode
    y = raw.find(b'\x00', x)
    path = raw[x+1:y]
    raw_sha = int.from_bytes(raw[y+1:y+21], "big")
    sha = format(raw_sha, "040x")
    return y+21, GitTreeLeaf(mode, path.decode("utf8"), sha)

def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = []
    while pos<max:
        pos,data = tree_parse_one(raw, pos)
        ret.append(data)
    return ret

def tree_leaf_sort_key(leaf):
    if leaf.mode.startswith(b"4"):
        return leaf.path + '/'
    else:
        return leaf.path
    
def tree_serialize(obj):
    obj.items.sort(key=tree_leaf_sort_key)
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path.encode('utf8')
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret

class GitTree(GitObject):
    fmt = b'tree'
    def deserialize(self, data):
        self.items = tree_parse(data)
    def serialize(self):
        return tree_serialize(self)
    def init(self):
        self.items = list()

argsp = argsubparser.add_parser("ls-tree", help = "Pretty-print a tree object")
argsp.add_argument("-r", dest="recursive", action="store_true", help="Recurse into sub-trees")
argsp.add_argument("tree", help="A tree-ish object")

def git_ls_tree(args):
    repo = repo_find()
    ls_tree(repo, args.tree, args.recursive)

def ls_tree(repo, ref, recursive = None, prefix = ""):
    print(repo)
    sha = object_find(repo, ref, fmt = b"tree")
    obj = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]
        
        match type:
            case b'04': type = 'tree'
            case b'10': type = 'blob'
            case b'12': type = 'blob' #symlink
            case b'16': type = 'commit'
            case _: raise Exception(f"Weird tree leaf mode {item.mode}")

        if not (recursive and type=='tree'):
            print(f"{'0' * (6 - len(item.mode)) + item.mode.decode('ascii')} {type} {item.sha}\t{os.path.join(prefix, item.path)}")
        else:
            ls_tree(repo, item.sha, recursive, os.path.join.prefix(prefix, item.path))

argsp = argsubparser.add_parser("checkout", help = "Checkout a commit inside a directory")
argsp.add_argument("commit", help="The commit or tree to checkout")
argsp.add_argument("path", help="The empty directory to checkout on")

def git_checkout(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.commit))
    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode('ascii'))
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception(f"Not a directory {args.path}")
        if os.listdir(args.path):
            raise Exception(f"Not Empty {args.path}")
    else:
        os.makedirs(args.path)

    tree_checkout(repo, obj, os.path.realpath(args.path))

def tree_checkout(repo, tree, path):
    for item in tree.items:
        obj = object.read(repo, item.sha)
        dest = os.path.join(path, item.path)
        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            with open(dest, "wb") as f:
                f.write(obj.blobdata)

def ref_resolve(repo, ref):
    path = repo_file(repo, ref)
    if not os.path.isfile(path):
        return None
    with open(path, 'r') as fp:
        data = fp.read()[:-1]
    if data.startswith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data

def ref_list(repo, path = None):
    if not path:
        path = repo_dir(repo, "refs")
    ret = dict()
    for f in sorted(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list(repo, can)
        else:
            ret[f] = ref_resolve(repo, can)
    return ret

argsp = argsubparser.add_parser("show-ref", help = "list references")
def git_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix = "refs")

def show_ref(repo, refs, with_hash = True, prefix = ""):
    if prefix:
        prefix = prefix + '/'
    for k, v in refs.items():
        if type(v) == str and with_hash:
            print(f"{v} {prefix}{k}")
        elif type(v) == str:
            print(f"{prefix}{k}")
        else:
            show_ref(repo, v, with_hash=with_hash, prefix=f"{prefix}{k}")

class GitTag(GitCommit):
    fmt = b'tag'

argsp = argsubparser.add_parser("tag", help = "List and create tags")
argsp.add_argument("-a", action="store_true", dest="create_tag_object", help="Whether to create a object")
argsp.add_argument("name", nargs="?", help="The new tags name")
argsp.add_argument("object", default="HEAD", nargs="?", help="The object the new tag will point to")
def git_tag(args):
    repo = repo_find()
    if args.name:
        tag_create(repo, args.name, args.object, create_tag_object = args.create_tag_object)
    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)

def tag_create(repo, name, ref, create_tag_object = False):
    sha = object_find(repo, ref)
    if create_tag_object:
        tag = GitTag()
        tag.kvlm = dict()
        tag.kvlm[b'object'] = sha.encode()
        tag.kvlm[b'type'] = b'commit'
        tag.kvlm[b'tag'] = name.encode()
        tag.kvlm[b'tagger'] = b'Soumy soumy@id.com'
        tag.kvlm[None] = b"A system generated message\n"
        tag_sha = object_write(tag, repo)
        ref_create(repo, "tags/" + name, tag_sha)
    else:
        ref_create(repo, "tags/"+name, sha)

def ref_create(repo, ref_name, sha):
    with open(repo_file(repo, "refs/"+ref_name), 'w') as f:
        f.write(sha+"\n")

def object_resolve(repo, name):
    """Resolve name to an object hash in repo
        This function is aware of:
        -The HEAD literal
        -short and long hashes
        -tags
        -branches
        -remote branches
    """
    candidates = list()
    hashRE = re.compile(r"^[0-9A-Fa-f]{4,40}$")
    if not name.strip():
        return None
    
    if name == "HEAD":
        return [ ref_resolve(repo, "HEAD") ]
    
    if hashRE.match(name):
        name = name.lower()
        prefix = name[0:2]
        path = repo_dir(repo, "objects", prefix, mkdir=False)
        if path:
            rem = name[2:]
            for f in os.listdir(path):
                if f.startswith(rem):
                    candidates.append(prefix+f)
    
    as_tag = ref_resolve(repo, "refs/tags/" + name)
    if as_tag:
        candidates.append(as_tag)

    as_branch = ref_resolve(repo, "refs/heads/" + name)
    if as_branch:
        candidates.append(as_branch)
    
    as_remote_branch = ref_resolve(repo, "refs/remotes/" + name)
    if as_remote_branch:
        candidates.append(as_remote_branch)
    return candidates

def object_find(repo, name, fmt = None, follow = True):
    sha = object_resolve(repo, name)
    if not sha:
        raise Exception(f"No such reference name {name}")
    if len(sha)>1:
        raise Exception(f"Ambiguous reference {name}: candidates are:\n - {'\n - '.join(sha)}.")
    sha = sha[0]
    if not fmt: return sha
    while True:
        obj = object_read(repo, sha)
        if obj.fmt == fmt:
            return sha
        
        if not follow:
            return None
        
        if obj.fmt == b'tag':
            sha = obj.kvlm[b'object'].decode('ascii')
        elif obj.fmt == b'commit' and fmt == b'tree':
            sha = obj.kvlm[b'tree'].decode('ascii')
        else:
            return None

argsp = argsubparser.add_parser("rev-parse", help="Parse revision ( or other objects ) identifiers")
argsp.add_argument("--wyag-type", metavar="type", dest="type", choices=["blob", "commit", "tree", "tag"], default=None, help ="Specify the expected type")
argsp.add_argument("name", help="The name to parse")

def git_rev_parse(args):
    if args.type:
        fmt = args.type.encode()
    else:
        fmt = None
    repo = repo_find()
    print(object_find(repo, args.name,fmt, follow=True))

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


    