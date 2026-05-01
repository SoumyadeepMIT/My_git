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
        f.write("ref: refs/heads/master\n")

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
        path = repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)
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
            val = [val]
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
        self.kvlm = kvlm_parse(data)
    
argsp = argsubparser.add_parser("log", help="Display history of a given commit")
argsp.add_argument("commit", default="HEAD", nargs="?", help="Commit to start at")
def log_graphviz(repo, sha, seen):
    if sha in seen:
        return
    seen.add(sha)
    print(sha)
    commit = object_read(repo, sha)
    message = commit.kvlm[None].decode("utf-8").strip()
    message = message.replace("\\", "\\\\")
    message = message.replace("\"", "\\\"")
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

class GitTreeLeaf(object):
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
            ls_tree(repo, item.sha, recursive, os.path.join(prefix, item.path))

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
        obj = object_read(repo, item.sha)
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

class GitIndexEntry(object):
    def __init__(self, ctime = None, mtime = None, dev = None, ino = None, mode_type = None, mode_perms = None,
                 uid = None, gid = None, fsize = None, sha = None, flag_assume_valid = None, flag_stage = None,
                 name = None):
        #The last time a file's metadata changed (seconds, nanoseconds)
        self.ctime = ctime
        #The last time a file's data changed
        self.mtime = mtime
        #The id of device containining this file
        self.dev = dev
        #The file's inode number
        self.ino = ino
        #The object type, b1000(regular) b1010(symlink) b1110(gitlink)
        self.mode_type = mode_type
        #The object permissions
        self.mode_perms = mode_perms
        #user id of owner
        self.uid = uid
        #Group id of owner
        self.gid = gid
        #Size of the object, in bytes
        self.fsize = fsize
        #The object's SHA
        self.sha = sha
        self.flag_assume_valid = flag_assume_valid
        self.flag_stage = flag_stage
        self.name = name

class GitIndex(object):
    version = None
    entries = []
    def __init__(self, version = 2, entries = None):
        if not entries:
            entries = list()
        self.version = version
        self.entries = entries

def index_read(repo):
    index_file = repo_file(repo, "index")

    # New repositories have no index!
    if not os.path.exists(index_file):
        return GitIndex()

    with open(index_file, 'rb') as f:
        raw = f.read()

    header = raw[:12]
    signature = header[:4]
    assert signature == b"DIRC" # Stands for "DirCache"
    version = int.from_bytes(header[4:8], "big")
    assert version == 2, "wyag only supports index file version 2"
    count = int.from_bytes(header[8:12], "big")

    entries = list()

    content = raw[12:]
    idx = 0
    for i in range(0, count):
        # Read creation time, as a unix timestamp (seconds since
        # 1970-01-01 00:00:00, the "epoch")
        ctime_s = int.from_bytes(content[idx: idx+4], "big")
        # Read creation time, as nanoseconds after that timestamp,
        # for extra precision.
        ctime_ns = int.from_bytes(content[idx+4: idx+8], "big")
        # Same for modification time: first seconds from epoch.
        mtime_s = int.from_bytes(content[idx+8: idx+12], "big")
        # Then extra nanoseconds
        mtime_ns = int.from_bytes(content[idx+12: idx+16], "big")
        # Device ID
        dev = int.from_bytes(content[idx+16: idx+20], "big")
        # Inode
        ino = int.from_bytes(content[idx+20: idx+24], "big")
        # Ignored.
        unused = int.from_bytes(content[idx+24: idx+26], "big")
        assert 0 == unused
        mode = int.from_bytes(content[idx+26: idx+28], "big")
        mode_type = mode >> 12
        assert mode_type in [0b1000, 0b1010, 0b1110]
        mode_perms = mode & 0b0000000111111111
        # User ID
        uid = int.from_bytes(content[idx+28: idx+32], "big")
        # Group ID
        gid = int.from_bytes(content[idx+32: idx+36], "big")
        # Size
        fsize = int.from_bytes(content[idx+36: idx+40], "big")
        # SHA (object ID).  We'll store it as a lowercase hex string
        # for consistency.
        sha = format(int.from_bytes(content[idx+40: idx+60], "big"), "040x")
        # Flags we're going to ignore
        flags = int.from_bytes(content[idx+60: idx+62], "big")
        # Parse flags
        flag_assume_valid = (flags & 0b1000000000000000) != 0
        flag_extended = (flags & 0b0100000000000000) != 0
        assert not flag_extended
        flag_stage = flags & 0b0011000000000000
        # Length of the name.  This is stored on 12 bits, some max
        # value is 0xFFF, 4095.  Since names can occasionally go
        # beyond that length, git treats 0xFFF as meaning at least
        # 0xFFF, and looks for the final 0x00 to find the end of the
        # name --- at a small, and probably very rare, performance
        # cost.
        name_length = flags & 0b0000111111111111

        # We've read 62 bytes so far.
        idx += 62

        if name_length < 0xFFF:
            assert content[idx + name_length] == 0x00
            raw_name = content[idx:idx+name_length]
            idx += name_length + 1
        else:
            print(f"Notice: Name is 0x{name_length:X} bytes long.")
            # This probably wasn't tested enough.  It works with a
            # path of exactly 0xFFF bytes.  Any extra bytes broke
            # something between git, my shell and my filesystem.
            null_idx = content.find(b'\x00', idx + 0xFFF)
            raw_name = content[idx: null_idx]
            idx = null_idx + 1

        # Just parse the name as utf8.
        name = raw_name.decode("utf8")

        # Data is padded on multiples of eight bytes for pointer
        # alignment, so we skip as many bytes as we need for the next
        # read to start at the right position.

        idx = 8 * ceil(idx / 8)

        # And we add this entry to our list.
        entries.append(GitIndexEntry(ctime=(ctime_s, ctime_ns),
                                     mtime=(mtime_s,  mtime_ns),
                                     dev=dev,
                                     ino=ino,
                                     mode_type=mode_type,
                                     mode_perms=mode_perms,
                                     uid=uid,
                                     gid=gid,
                                     fsize=fsize,
                                     sha=sha,
                                     flag_assume_valid=flag_assume_valid,
                                     flag_stage=flag_stage,
                                     name=name))

    return GitIndex(version=version, entries=entries)

argsp = argsubparser.add_parser("ls-files", help = "List all the stage files")
argsp.add_argument("--verbose", action="store_true", help="show everything")

def git_ls_files(args):
    repo = repo_find()
    index = index_read(repo)
    if args.verbose:
        print(f"Index file format v{index.version}, containing {len(index.entries)} entries")
    for e in index.entries:
        print(e.name)
        if args.verbose:
            entry_type = { 0b1000: "regular file",
                           0b1010: "symlink",
                           0b1110: "git link"}[e.mode_type]
            print(f"{entry_type} with perms: {e.mode_perms:o}")
            print(f"on blob: {e.sha}")
            print(f"created: {datetime.fromtimestamp(e.ctime[0])}.{e.ctime[1]}, modified: {datetime.fromtimestamp(e.mtime[0])}.{e.mtime[1]}")
            print(f"device: {e.dev}, inode: {e.ino}")
            try:
                print(f"User : {pwd.getpwuid(e.uid)}.pw_name ({e.uid}) group: {grp.getgrgid(e.gid).gr_name} ({e.gid})")
            except NameError:
                print(f"user: {e.uid} group:{e.gid}")
            print(f"flags: stage={e.flag_stage} assume_valid={e.flag_assume_valid}")

argsp = argsubparser.add_parser("check-ignore", help="check paths agains ignore rules")
argsp.add_argument("path", nargs="+", help = "Paths to check")

def git_check_ignore(args):
    repo = repo_find()
    rules = gitignore_read(repo)
    for path in args.path:
        if check_ignore(rules, path):
            print(path)

def gitignore_parse1(raw):
    raw = raw.strip()
    if not raw or raw[0] == "#":
        return None
    elif raw[0] == '!':
        return (raw[1:], False)
    elif raw[0] == "\\":
        return (raw[1:], True)
    else:
        return (raw, True)
    
def gitignore_parse(lines):
    ret = list()
    for line in lines:
        parsed = gitignore_parse1(line)
        if parsed:
            ret.append(parsed)
    return ret

class GitIgnore(object):
    absolute = None
    scoped = None
    def __init__(self, absolute, scoped):
        self.absolute = absolute
        self.scoped = scoped

def gitignore_read(repo):
    ret = GitIgnore(absolute=[], scoped={})
    repo_file = os.path.join(repo.gitdir, "info/exclude")
    if os.path.exists(repo_file):
        with open(repo_file, "r") as f:
            ret.abolute.append(gitignore_parse(f.readlines()))
        
    if "XDG_CONFIG_HOME" in os.environ:
        config_home = os.environ["XDG_CONFIF_HOME"]
    else:
        config_home = os.path.expanduser("~/.config")
    global_file = os.path.join(config_home, "git/ignore")
    if os.path.exists(global_file):
        with open(global_file, "r") as f:
            ret.abolute.append(gitignore_parse(f.readlines()))
    index = index_read(repo)
    for entry in index.entries:
        if entry.name == ".gitignore" or entry.name.endswith("/.gitignore"):
            dir_name = os.path.dirname(entry.name)
            contents = object_read(repo, entry.sha)
            lines = contents.blobdata.decode("utf8").splitlines()
            ret.scoped[dir_name] = gitignore_parse(lines)
    return ret

def check_ignore1(rules, path):
    result = None
    for (pattern, value) in rules:
        if fnmatch(path, pattern):
            result = value
    return result

def check_ignore_scoped(rules, path):
    parent = os.path.dirname(path)
    while True:
        if parent in rules:
            result = check_ignore1(rules[parent], path)
            if result != None:
                return result
        if parent =="": break
        parent = os.path.dirname(parent)
    return None
def check_ignore_absolute(rules, path):
    parent = os.path.dirname(path)
    for ruleset in rules:
        result = check_ignore1(ruleset, path)
        if result != None:
            return result
    return False

def check_ignore(rules, path):
    if os.path.isabs(path):
        raise Exception("This function requires path to be relative to the repo's root")
    result = check_ignore_scoped(rules.scoped, path)
    if result!=None:
        return result
    return check_ignore_absolute(rules.absolute, path)

argsp = argsubparser.add_parser("status", help="show the working of tree status.")
def git_status(_):
    repo = repo_find()
    index = index_read(repo)
    cmd_status_branch(repo)
    cmd_status_head_index(repo, index)
    print()
    cmd_status_index_worktree(repo, index)

def branch_get_active(repo):
    with open(repo_file(repo, "HEAD"), "r") as f:
        head = f.read()
    if head.startswith("ref: refs/heads/"):
        return (head[16:-1])
    else:
        return False
    
def cmd_status_branch(repo):
    branch = branch_get_active(repo)
    if branch:
        print(f"On branch {branch}")
    else:
        print(f"HEAD detached at {object_find(repo, 'HEAD')}")

def tree_to_dict(repo, ref, prefix = ""):
    ret = dict()
    tree_sha = object_find(repo, ref, fmt = b'tree')
    tree = object_read(repo, tree_sha)
    for leaf in tree.items:
        full_path = os.path.join(prefix, leaf.path)
        is_subtree = leaf.mode.startswith(b'04')
        if is_subtree:
            ret.update(tree_to_dict(repo, leaf.sha, full_path))
        else:
            ret[full_path] = leaf.sha
    return ret

def cmd_status_head_index(repo, index):
    print("Changes to be committed")
    head = tree_to_dict(repo, "HEAD")
    for entry in index.entries:
        if entry.name in head:
            if head[entry.name] != entry.sha: # Files in index and branch tree, but modified
                print("  modified:", entry.name)
            del head[entry.name] # Delete the key
        else:
            print("  added:", entry.name) # New files, not in branch tree, but in index
    
    for entry in head.keys():
        print("  deleted:", entry) # Deleted files, in branch tree but not in index

def cmd_status_index_worktree(repo, index):
    print("Changes not staged for commit")
    ignore = gitignore_read(repo)
    gitdir_prefix = repo.gitdir + os.path.sep
    all_files = list()
    for (root, _, files) in os.walk(repo.worktree, True):
        if repo == repo.gitdir or root.startswith(gitdir_prefix):
            continue
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo.worktree)
            all_files.append(rel_path)
    #Compare real files with the index (staging area) files
    for entry in index.entries:
        full_path = os.path.join(repo.worktree, entry.name)
        if not os.path.exists(full_path):
            print(" deleted: ", entry.name)
        else:
            stat = os.stat(full_path)
            ctime_ns = entry.ctime[0] * 10**9 + entry.ctime[1]
            mtime_ns = entry.mtime[0] * 10**9 + entry.mtime[1]
            if (stat.st_ctime_ns != ctime_ns) or (stat.st_mtime_ns != mtime_ns):
                with open(full_path, "rb") as f:
                    new_sha = object_hash(f, b"blob", None)
                    same = entry.sha == new_sha
                    if not same:
                        print("  modified:", entry.name)

        if entry.name in all_files:
            all_files.remove(entry.name)

    print()
    print("Untracked files:")
    for f in all_files:
        if not check_ignore(ignore, f):
            print(" ", f)

def index_write(repo, index):
    with open(repo_file(repo, "index"), "wb") as f:

        # HEADER

        # Write the magic bytes.
        f.write(b"DIRC")
        # Write version number.
        f.write(index.version.to_bytes(4, "big"))
        # Write the number of entries.
        f.write(len(index.entries).to_bytes(4, "big"))

        # ENTRIES

        idx = 0
        for e in index.entries:
            f.write(e.ctime[0].to_bytes(4, "big"))
            f.write(e.ctime[1].to_bytes(4, "big"))
            f.write(e.mtime[0].to_bytes(4, "big"))
            f.write(e.mtime[1].to_bytes(4, "big"))
            f.write(e.dev.to_bytes(4, "big"))
            f.write(e.ino.to_bytes(4, "big"))

            # Mode
            mode = (e.mode_type << 12) | e.mode_perms
            f.write(mode.to_bytes(4, "big"))

            f.write(e.uid.to_bytes(4, "big"))
            f.write(e.gid.to_bytes(4, "big"))

            f.write(e.fsize.to_bytes(4, "big"))
            # @FIXME Convert back to int.
            f.write(int(e.sha, 16).to_bytes(20, "big"))

            flag_assume_valid = 0x1 << 15 if e.flag_assume_valid else 0

            name_bytes = e.name.encode("utf8")
            bytes_len = len(name_bytes)
            if bytes_len >= 0xFFF:
                name_length = 0xFFF
            else:
                name_length = bytes_len

            # We merge back three pieces of data (two flags and the
            # length of the name) on the same two bytes.
            f.write((flag_assume_valid | e.flag_stage | name_length).to_bytes(2, "big"))

            # Write back the name, and a final 0x00.
            f.write(name_bytes)
            f.write((0).to_bytes(1, "big"))

            idx += 62 + len(name_bytes) + 1

            # Add padding if necessary.
            if idx % 8 != 0:
                pad = 8 - (idx % 8)
                f.write((0).to_bytes(pad, "big"))
                idx += pad

argsp = argsubparser.add_parser("rm", help="Remove files from the working tree and the index")
argsp.add_argument("path", nargs="+", help="Files to remove")
def git_rm(args):
    repo = repo_find()
    rm(repo, args.path)

def rm(repo, paths, delete = True, skip_missing = False):
    index = index_read(repo)
    worktree = repo.worktree + os.sep
    abspath = set()
    for path in paths:
        absp = os.path.abspath(path)
        if absp.startswith(worktree):
            abspath.add(absp)
        else:
            raise Exception(f"Cannot remove paths outside of worktree: {paths}")
        
    kept_entries = list()
    remove = list()
    for e in index.entries:
        full_path = os.path.join(repo.worktree, e.name)
        if full_path in abspath:
            remove.append(full_path)
            abspath.remove(full_path)
        else:
            kept_entries.append(e)
    
    if len(abspath) > 0 and not skip_missing:
        raise Exception(f"Cannot remove paths not in index:{abspath}")
    if delete:
        for path in remove:
            os.unlink(path)
    index.entries = kept_entries
    index_write(repo, index)

argsp = argsubparser.add_parser("add", help="Add file contents to index")
argsp.add_argument("path", nargs="+", help="Files to add")

def git_add(args):
    repo = repo_find()
    add(repo, args.path)

def add(repo, paths, delete=True, skip_missing=False):

    # First remove all paths from the index, if they exist.
    rm (repo, paths, delete=False, skip_missing=True)

    worktree = repo.worktree + os.sep

    # Convert the paths to pairs: (absolute, relative_to_worktree).
    # Also delete them from the index if they're present.
    clean_paths = set()
    for path in paths:
        abspath = os.path.abspath(path)
        if not (abspath.startswith(worktree) and os.path.isfile(abspath)):
            raise Exception(f"Not a file, or outside the worktree: {paths}")
        relpath = os.path.relpath(abspath, repo.worktree)
        clean_paths.add((abspath,  relpath))

    # Find and read the index.  It was modified by rm.  (This isn't
    # optimal, good enough for wyag!)
    #
    # commands instead of reading and writing it over again.
    index = index_read(repo)

    for (abspath, relpath) in clean_paths:
        with open(abspath, "rb") as fd:
            sha = object_hash(fd, b"blob", repo)

            stat = os.stat(abspath)

            ctime_s = int(stat.st_ctime)
            ctime_ns = stat.st_ctime_ns % 10**9
            mtime_s = int(stat.st_mtime)
            mtime_ns = stat.st_mtime_ns % 10**9

            entry = GitIndexEntry(ctime=(ctime_s, ctime_ns), mtime=(mtime_s, mtime_ns), dev=stat.st_dev, ino=stat.st_ino,
                                  mode_type=0b1000, mode_perms=0o644, uid=stat.st_uid, gid=stat.st_gid,
                                  fsize=stat.st_size, sha=sha, flag_assume_valid=False,
                                  flag_stage=False, name=relpath)
            index.entries.append(entry)

    # Write the index back
    index_write(repo, index)

argsp = argsubparser.add_parser("commit", help="Record changes to the repository")
argsp.add_argument("-m", metavar="message", dest = "message", help = "Message to associate with the commit")
def gitconfig_read():
    xdg_config_home = os.environ["XDG_CONFIG_HOME"] if "XDG_CONFIG_HOME" in os.environ else "~/config"
    config_files = [os.path.expanduser(os.path.join(xdg_config_home, "git/config")),
                    os.path.expanduser("~/.gitconfig")]
    config = configparser.ConfigParser()
    config.read(config_files)
    return config

def gitconfig_user_get(config):
    if "user" in config:
        if "name" in config["user"] and "email" in config["user"]:
            return f"{config["user"]["name"]} < {config["user"]["email"]}>"
    return None

def tree_from_index(repo, index):
    contents = dict()
    contents[""] = list()
    for entry in index.entries:
        dirname = os.path.dirname(entry.name)
        key = dirname
        while key != "":
            if not key in contents:
                contents[key] = list()
            key = os.path.dirname(key)
        contents[dirname].append(entry)
    sorted_paths = sorted(contents.keys(), key = len, reverse = True)
    sha = None
    for path in sorted_paths:
        tree = GitTree()
        for entry in contents[path]:
            if isinstance(entry, GitIndexEntry):
                leaf_mode = f"{entry.mode_type:02o}{entry.mode_perms:04o}".encode("ascii")
                leaf = GitTreeLeaf(mode = leaf_mode, path = os.path.basename(entry.name), sha = entry.sha)
            else:
                leaf = GitTreeLeaf(mode = b"040000", path = entry[0], sha = entry[1])
            tree.items.append(leaf)
        sha = object_write(tree, repo)
        parent = os.path.dirname(path)
        base = os.path.basename(path)
        contents[parent].append((base, sha))
    return sha


def commit_create(repo, tree, parent, author, timestamp, message):
    commit = GitCommit()
    commit.kvlm[b"tree"] = tree.encode("ascii")
    if parent:
        commit.kvlm[b"parent"] = parent.encode("ascii")
    message = message.strip() + "\n"
    offset = int(timestamp.astimezone().utcoffset().total_seconds())
    hours = offset//3600
    minutes = (offset % 3600) // 60
    tz = "{}{:02}{:02}".format("+" if offset>0 else "-", hours, minutes)
    author = author + " " + str(int(timestamp.timestamp())) + " " + tz
    commit.kvlm[b"author"] = author.encode("utf8")
    commit.kvlm[b"committer"] = author.encode("utf8")
    commit.kvlm[None] = message.encode("utf8")
    return object_write(commit, repo)

def git_commit(args):
    repo = repo_find()
    index = index_read(repo)
    tree = tree_from_index(repo, index)
    commit = commit_create(repo, tree, object_find(repo, "HEAD"), "soumy", datetime.now(), args.message)
    active_branch = branch_get_active(repo)
    if active_branch:
        with open(repo_file(repo, os.path.join("refs/heads", active_branch)), "w") as f:
            f.write(commit + "\n")
    else:
        with open(repo_file(repo, "HEAD"), "w") as f:
            f.write("\n")
    print(f"commit succesful in {active_branch} with id {commit}")

def main(argv = sys.argv[1:]):
    args=argparser.parse_args(argv)
    match args.command:
        case 'init': git_init(args)
        case 'add': git_add(args)
        case 'commit': git_commit(args)
        case 'log': git_log(args)
        case 'status': git_status(args)
        case 'checkout': git_checkout(args)
        case 'cat-file': git_cat_file(args)
        case 'check-ignore': git_check_ignore(args)
        case 'ls-files': git_ls_files(args)
        case 'hash-object': git_hash_object(args)
        case 'rev-parse': git_rev_parse(args)
        case 'tag': git_tag(args)
        case 'ls-tree': git_ls_tree(args)
        case 'rm': git_rm(args)
        case 'show-ref': git_show_ref(args)
        case _: print(f'Unknown command: {args.command}')


    