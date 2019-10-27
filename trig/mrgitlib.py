#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import getopt
import re
import tempfile
import shutil
import filecmp
import glob
import pipes
from os.path import join as pjoin
from os.path import abspath, normpath, basename, dirname

import gitinterface as gititf
from gitinterface import change_directory


REPO_MAP_BRANCH = 'mrgit_repo_map'
REPOMAP_FILENAME = 'repomap'
REPOMAP_TEMPFILE = 'repomap.tmp'


class MRGitExitError( Exception ):
    pass


def errorexit( *args ):
    ""
    err = ' '.join( [ str(arg) for arg in args ] )
    raise MRGitExitError( err )


def clone( argv ):
    ""
    optL,argL = getopt.getopt( argv, 'G', [] )

    optD = {}
    for n,v in optL:
        optD[n] = v

    if len( argL ) > 0:

        urls, directory = parse_url_list( argL )
        assert len( urls ) > 0

        cfg = Configuration()

        if '-G' in optD:
            if len(urls) != 1:
                errorexit( 'must specify exactly one URL with the -G option' )
            clone_from_google_repo_manifests( cfg, urls[0], directory )

        elif len( urls ) == 1:
            clone_from_single_url( cfg, urls[0], directory )

        else:
            clone_from_multiple_urls( cfg, urls, directory )

        cfg.commitLocalRepoMap()


def init( argv ):
    ""
    cfg = Configuration()
    cfg.setTopDir( os.getcwd() )
    cfg.createMRGitRepo()


def fetch( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopDir()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitInterface( rootdir=pjoin( top, path ) )
        git.run( 'fetch', verbose=3 )


def pull( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopDir()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitInterface( rootdir=pjoin( top, path ) )
        git.run( 'pull', verbose=3 )


def add( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopDir()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitInterface( rootdir=pjoin( top, path ) )
        args = [ pipes.quote(arg) for arg in argv ]
        git.run( 'add', *args, verbose=3 )


def commit( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopDir()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitInterface( rootdir=pjoin( top, path ) )
        args = [ pipes.quote(arg) for arg in argv ]
        git.run( 'commit', *args, verbose=3 )


def push( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopDir()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitInterface( rootdir=pjoin( top, path ) )
        git.run( 'push', verbose=3 )


def load_configuration():
    ""
    cfg = Configuration()
    top = find_mrgit_top_level()
    cfg.setTopDir( top )
    git = gititf.GitInterface( rootdir=top+'/.mrgit' )
    cfg.loadManifests( git )
    cfg.computeLocalRepoMap()

    return cfg


def find_mrgit_top_level():
    ""
    top = None

    d1 = os.getcwd()
    while True:
        if os.path.isdir( pjoin( d1, '.mrgit' ) ):
            top = d1
            break
        d2 = dirname( d1 )
        if not d2 or d1 == d2:
            break
        d1 = d2

    return top


def parse_url_list( args ):
    ""
    directory = None

    if len( args ) <= 1 or \
       gititf.repository_url_match( args[-1] ) or \
       gititf.is_a_local_repository( args[-1] ) or \
       gititf.is_a_local_repository( args[-1]+'/.mrgit' ):
        urls = list( args )
    else:
        directory = args[-1]
        urls = args[:-1]

    urls = abspath_local_repository_urls( urls )

    return urls, directory


def abspath_local_repository_urls( urls ):
    ""
    newurls = []
    for url in urls:
        if gititf.is_a_local_repository( url ):
            newurls.append( abspath( url ) )
        else:
            newurls.append( url )

    return newurls


def clone_from_single_url( cfg, url, directory ):
    ""
    tmpd = TempDirectory( directory )

    try:
        # prefer an .mrgit repo under the given url
        git = clone_repo( url+'/.mrgit', tmpd.path(), verbose=1 )
        baseurl = url

    except gititf.GitInterfaceError:
        # that failed, so just clone the given url
        tmpd.removeFiles()
        git = clone_repo( url, tmpd.path() )
        baseurl = dirname( url )

    if check_load_mrgit_repo( cfg, baseurl, git ):

        # we just cloned an mrgit manifests repo
        cfg.computeLocalRepoMap()
        urlname = gititf.repo_name_from_url( baseurl )
        topdir = cfg.setTopDir( directory, urlname )
        tmpd.moveTo( topdir+'/.mrgit' )
        clone_repositories_from_config( cfg )

    else:
        # repo is not an mrgit manifests
        cfg.createFromURLs( [ url ] )
        cfg.computeLocalRepoMap()
        topdir = cfg.setTopDir( directory )
        tmpd.moveTo( topdir )
        cfg.createMRGitRepo()


def clone_from_multiple_urls( cfg, urls, directory ):
    ""
    cfg.createFromURLs( urls )
    cfg.computeLocalRepoMap()
    cfg.setTopDir( directory )
    clone_repositories_from_config( cfg )
    cfg.createMRGitRepo()


def clone_from_google_repo_manifests( cfg, url, directory ):
    ""
    tmpd = TempDirectory( directory )

    git = clone_repo( url, tmpd.path() )

    gconv = GoogleConverter( tmpd.path() )
    gconv.readManifestFiles()
    gconv.createRemoteURLMap( cfg )
    gconv.createRepoGroups( cfg )

    cfg.computeLocalRepoMap()
    topdir = cfg.setTopDir( directory )
    cfg.createMRGitRepo()
    tmpd.moveTo( pjoin( topdir, '.mrgit', 'google_manifests' ) )
    clone_repositories_from_config( cfg )


def load_config_from_google_manifests( cfg, git ):
    ""
    import xml.etree.ElementTree as ET

    with change_directory( git.getRootDir() ):

        parse_google_manifest_file( 'default.xml' )

        for fn in glob.glob( '*.xml' ):

            groupname = os.path.splitext(fn)[0]

            root = ET.parse( fn ).getroot()
            baseurl = get_xml_remote_url( root )

        for nd in root:
            if nd.tag == 'project':
                name = nd.attrib['name']
                path = nd.attrib['path']
                cfg.addManifestRepo( groupname, name, path )


class GoogleConverter:

    def __init__(self, manifests_directory):
        ""
        self.srcdir = manifests_directory

    def readManifestFiles(self):
        ""
        fn = pjoin( self.srcdir, 'default.xml' )
        self.default = GoogleManifestReader( fn )
        self.default.createRepoNameToURLMap()

        self.manifests = []
        for fn in glob.glob( pjoin( self.srcdir, '*.xml' ) ):
            gmr = GoogleManifestReader( fn )
            gmr.createRepoNameToURLMap()
            self.manifests.append( gmr )

    def getPrimaryURL(self, repo_name):
        """
        The repo XML syntax allows for different Git remote URLs for the
        same repository name.  The "primary" URL for a repository name is
        the one specified in the defaults.xml, or if not there then it is
        the most common one in all of the manifest XML files.
        """
        url = self.default.getRepoURL( repo_name, None )

        if not url:
            url2cnt = self._count_urls( repo_name )
            sortL = [ (T[1],T[0]) for T in url2cnt.items() ]
            sortL.sort()
            url = sortL[-1][1]

        return url

    def createRemoteURLMap(self, cfg):
        ""
        for gmr in [ self.default ] + self.manifests:
            for reponame in gmr.getRepoNames():
                url = self.getPrimaryURL( reponame )
                cfg.addRepoURL( reponame, url )

    def createRepoGroups(self, cfg):
        ""
        for gmr in [ self.default ] + self.manifests:
            self._create_group_from_manifest( gmr, cfg )

    def _create_group_from_manifest(self, gmr, cfg):
        ""
        if self._all_urls_are_primary( gmr ):
            for name,url,path in gmr.getProjectList():
                groupname = gmr.getGroupName()
                cfg.addManifestRepo( groupname, name, path )

    def _all_urls_are_primary(self, gmr):
        ""
        for name,url,path in gmr.getProjectList():
            primary = self.getPrimaryURL( name )
            if url != primary:
                return False

        return True

    def _count_urls(self, repo_name):
        ""
        url2cnt = {}

        for mfest in self.manifests:
            url = mfest.getRepoURL( repo_name, None )
            if url:
                url2cnt[ url ] = url2cnt.get( url, 0 ) + 1

        return url2cnt


class GoogleManifestReader:

    def __init__(self, filename):
        ""
        # put this here instead of the top of this file because reading Google
        # manifests is not core to mrgit, but if it was at the top and the
        # import failed, then the application would crash
        import xml.etree.ElementTree as ET

        self.name = os.path.splitext( basename( filename ) )[0]
        self.urlmap = {}

        self.xmlroot = ET.parse( filename ).getroot()

    def createRepoNameToURLMap(self):
        ""
        self.urlmap = {}

        self.default_remote = self._get_default_remote_name()
        self.remotes = self._collect_remote_prefix_urls()

        for nd in self.xmlroot:
            if nd.tag == 'project':
                url = self._get_project_url( nd )
                name = self._get_project_name( nd )

                assert name not in self.urlmap
                self.urlmap[name] = url

        return self.urlmap

    def getGroupName(self):
        ""
        return self.name

    def getRepoNames(self):
        ""
        return self.urlmap.keys()

    def getRepoURL(self, repo_name, *default):
        ""
        if len(default) > 0:
            return self.urlmap.get( repo_name, default[0] )
        return self.urlmap[repo_name]

    def getProjectList(self):
        ""
        projects = []

        for nd in self.xmlroot:
            if nd.tag == 'project':
                name = self._get_project_name( nd )
                url = self.urlmap[ name ]
                path = self._get_project_path( nd )

                projects.append( ( name, url, path ) )

        return projects

    def _collect_remote_prefix_urls(self):
        ""
        remotes = {}

        for nd in self.xmlroot:
            if nd.tag == 'remote':
                name = nd.attrib['name'].strip()
                prefix = nd.attrib['fetch'].strip()
                remotes[name] = prefix

        return remotes

    def _get_project_name(self, xmlnd):
        ""
        return xmlnd.attrib['name'].strip()

    def _get_project_url(self, xmlnd):
        ""
        name = self._get_project_name( xmlnd )
        remote = xmlnd.attrib.get( 'remote', self.default_remote ).strip()
        prefix = self.remotes[remote]
        url = append_path_to_url( prefix, name )

        return url

    def _get_project_path(self, xmlnd):
        ""
        path = xmlnd.attrib.get( 'path', '.' )
        if not path: path = '.'
        path = normpath( path )

        return path

    def _get_default_remote_name(self):
        ""
        for nd in self.xmlroot:
            if nd.tag == 'default':
                return nd.attrib['remote'].strip()


def clone_repositories_from_config( cfg ):
    ""
    topdir = cfg.getTopDir()

    check_make_directory( topdir )

    with change_directory( topdir ):
        for url,loc in cfg.getRemoteRepoList():
            clone_repo( url, loc )


def clone_repo( url, into_dir, verbose=2 ):
    ""
    git = gititf.GitInterface()

    if os.path.exists( into_dir ):

        assert '.git' not in os.listdir( into_dir )

        tmp = tempfile.mkdtemp( '', 'mrgit_tempclone_', abspath( into_dir ) )
        git.clone( url, tmp, verbose=verbose )
        move_directory_contents( tmp, into_dir )

        git = gititf.GitInterface( rootdir=into_dir )

    else:
        git.clone( url, into_dir, verbose=verbose )

    return git


class TempDirectory:

    def __init__(self, subdir):
        """
        if 'subdir' is None, create tmpdir1/tmpdir2
        else, create subdir/tmpdir2
        """
        self.subdir = subdir
        self.tmpdir = self._create()

    def path(self):
        ""
        return self.tmpdir

    def removeFiles(self):
        ""
        remove_all_files_in_directory( self.tmpdir )

    def moveTo(self, todir):
        """
        contents of temp dir are moved inside 'todir', and temp dir is removed
        """
        if os.path.exists( todir ):
            move_directory_contents( self.tmpdir, todir )
        else:
            check_make_directory( dirname( todir ) )
            os.rename( self.tmpdir, todir )

        if not self.subdir:
            shutil.rmtree( dirname( self.tmpdir ) )

    def _create(self):
        ""
        check_make_directory( self.subdir )

        if self.subdir:
            tdir = abspath( self.subdir )
            tmpdir = tempfile.mkdtemp( '', 'mrgit_tempclone_', tdir )
        else:
            tmpdir1 = tempfile.mkdtemp( '', 'mrgit_tempclone_', os.getcwd() )
            tmpdir  = tempfile.mkdtemp( '', 'mrgit_tempclone_', tmpdir1 )

        return tmpdir


def check_load_mrgit_repo( cfg, baseurl, git ):
    ""
    mfestfn = pjoin( git.getRootDir(), 'manifests' )

    if os.path.isfile( mfestfn ):
        if REPO_MAP_BRANCH in git.listBranches() or \
           REPO_MAP_BRANCH in git.listRemoteBranches():

            cfg.loadManifests( git )
            cfg.loadRepoMap( git, baseurl )
            return True

    return False


def remove_all_files_in_directory( path ):
    ""
    for fn in os.listdir( path ):
        dfn = pjoin( path, fn )
        if os.path.isdir( dfn ):
            shutil.rmtree( dfn )
        else:
            os.remove( dfn )


def move_directory_contents( fromdir, todir ):
    ""
    if os.path.exists( todir ):
        for fn in os.listdir( fromdir ):
            frompath = pjoin( fromdir, fn )
            shutil.move( frompath, todir )
        shutil.rmtree( fromdir )

    else:
        os.rename( fromdir, todir )


def check_make_directory( path ):
    ""
    if path and not os.path.isdir( path ):
        os.mkdir( path )


class Configuration:
    """
    The manifests describe repo groupings and the repo layouts for each.

    The remote maps a repository name to the upstream repo URL.

    The local maps a repository name to the local repo directory path.
    """

    def __init__(self):
        ""
        self.topdir = None
        self.mfest = Manifests()
        self.remote = RepoMap()
        self.local = RepoMap()

    def createFromURLs(self, urls):
        ""
        groupname = None
        for i,url in enumerate(urls):
            name = gititf.repo_name_from_url( url )
            if i == 0:
                groupname = name
                path = '.'
            else:
                path = name

            self.mfest.addRepo( groupname, name, path )
            self.remote.setRepoLocation( name, url=url )

    def loadManifests(self, git):
        ""
        read_mrgit_manifests_file( self.mfest, git )

    def loadRepoMap(self, git, baseurl):
        ""
        read_mrgit_repo_map_file( self.remote, baseurl, git )

    def addRepoURL(self, reponame, url):
        ""
        self.remote.setRepoLocation( reponame, url )

    def addManifestRepo(self, groupname, reponame, path):
        ""
        self.mfest.addRepo( groupname, reponame, path )

    def computeLocalRepoMap(self):
        ""
        grp = self.mfest.findGroup( None )

        if grp != None:
            for spec in grp.getRepoList():
                self.local.setRepoLocation( spec['repo'], path=spec['path'] )

    def setTopDir(self, directory, urlname=None):
        ""
        if directory:
            self.topdir = abspath( normpath( directory ) )
        else:
            grp = self.mfest.findGroup( None )
            if grp == None:
                self.topdir = abspath( urlname )
            else:
                self.topdir = abspath( grp.getName() )

        return self.topdir

    def getTopDir(self):
        ""
        return self.topdir

    def getLocalRepoPaths(self):
        ""
        paths = []

        grp = self.mfest.findGroup( None )
        if grp != None:
            for spec in grp.getRepoList():
                paths.append( spec['path'] )

        return paths

    def getRemoteRepoList(self):
        ""
        repolist = []

        grp = self.mfest.findGroup( None )

        if grp != None:
            for spec in grp.getRepoList():
                url = self.remote.getRepoURL( spec['repo'] )
                path = spec['path']
                repolist.append( [ url, path ] )

        return repolist

    def commitLocalRepoMap(self):
        ""
        mrgit = pjoin( self.topdir, '.mrgit' )
        git = gititf.GitInterface( rootdir=mrgit )
        git.checkoutBranch( REPO_MAP_BRANCH )

        try:
            write_mrgit_repo_map_file( self.local, git )
        finally:
            git.checkoutBranch( 'master' )

    def createMRGitRepo(self):
        ""
        repodir = pjoin( self.topdir, '.mrgit' )

        git = gititf.GitInterface()
        git.create( repodir, verbose=3 )

        self.mfest.writeToFile( repodir+'/manifests' )
        git.add( 'manifests' )
        git.commit( 'init manifests' )

        git.createBranch( REPO_MAP_BRANCH )
        write_mrgit_repo_map_file( self.local, git )
        git.checkoutBranch( 'master' )

    def getRemoteRepoMap(self):
        ""
        return self.remote

    def getManifests(self):
        ""
        return self.mfest


class Manifests:

    def __init__(self):
        ""
        self.groups = []

    def addRepo(self, groupname, reponame, path):
        ""
        grp = self.findGroup( groupname, create=True )
        grp.setRepo( reponame, path )

    def findGroup(self, groupname, create=False):
        ""
        grp = None

        if not groupname:
            if len( self.groups ) > 0:
                grp = self.groups[0]

        else:
            for igrp in self.groups:
                if igrp.getName() == groupname:
                    grp = igrp
                    break

            if not grp and create:
                grp = RepoGroup( groupname )
                self.groups.append( grp )

        return grp

    def writeToFile(self, filename):
        ""
        with open( filename, 'w' ) as fp:
            for grp in self.groups:
                fp.write( '[ group '+grp.getName()+' ]\n' )
                for spec in grp.getRepoList():
                    fp.write( '    repo='+spec['repo'] )
                    fp.write( ', path='+spec['path'] )
                    fp.write( '\n' )

                fp.write( '\n' )

    def readFromFile(self, fileobj):
        ""
        groupname = None

        for line in fileobj:
            line = line.strip()
            if line.startswith( '#' ):
                pass
            elif line.startswith( '[' ):
                groupname = None
                sL = line.strip('[').strip(']').strip().split()
                if len(sL) == 2 and sL[0] == 'group':
                    groupname = sL[1]
            elif groupname:
                attrs = parse_attribute_line( line )
                if 'repo' in attrs and 'path' in attrs:
                    self.addRepo( groupname, attrs['repo'], attrs['path'] )


class RepoGroup:

    def __init__(self, groupname):
        ""
        self.name = groupname
        self.repos = []

    def getName(self):
        ""
        return self.name

    def getRepoList(self):
        ""
        return self.repos

    def setRepo(self, reponame, path):
        ""
        spec = self.findRepo( reponame, create=True )
        spec['path'] = path

    def findRepo(self, reponame, create=False):
        ""
        for spec in self.repos:
            if spec['repo'] == reponame:
                return spec

        if create:
            spec = { 'repo':reponame }
            self.repos.append( spec )
            return spec

        return None

    def getRepoNames(self):
        ""
        nameL = [ spec['repo'] for spec in self.repos ]
        return nameL

    def getRepoPath(self, reponame):
        ""
        spec = self.findRepo( reponame )
        return spec['path']


class RepoMap:

    def __init__(self):
        ""
        self.repomap = {}

    def setRepoLocation(self, reponame, url=None, path=None):
        ""
        self.repomap[ reponame ] = ( url, path )

    def getRepoURL(self, reponame):
        ""
        return self.repomap[ reponame ][0]

    def writeToFile(self, filename):
        ""
        with open( filename, 'w' ) as fp:
            for name,loc in self.repomap.items():
                fp.write( 'repo='+name )
                if loc[0]:
                    fp.write( ', url='+loc[0] )
                if loc[1]:
                    fp.write( ', path='+loc[1] )
                fp.write( '\n' )

            fp.write( '\n' )

    def readFromFile(self, baseurl):
        ""
        with open( REPOMAP_FILENAME, 'r' ) as fp:

            for line in fp:
                line = line.strip()

                if line.startswith('#'):
                    pass

                elif line:
                    attrs = parse_attribute_line( line )
                    if 'repo' in attrs:
                        if 'url' in attrs:
                            url = attrs['url']
                        else:
                            url = append_path_to_url( baseurl, attrs['path'] )

                        self.setRepoLocation( attrs['repo'], url=url )


def append_path_to_url( url, path ):
    ""
    url = url.rstrip('/').rstrip(os.sep)
    path = normpath( path )

    if not path or path == '.':
        return url
    else:
        assert not path.startswith('..')
        return pjoin( url, path )


def parse_attribute_line( line ):
    ""
    attrs = {}

    kvL = [ s.strip() for s in line.split(',') ]
    for kvstr in kvL:
        kv = [ s.strip() for s in kvstr.split( '=', 1 ) ]
        if len(kv) == 2 and kv[0]:
            attrs[ kv[0] ] = kv[1]

    return attrs


def read_mrgit_manifests_file( manifests, git ):
    ""
    fn = pjoin( git.getRootDir(), 'manifests' )

    git.checkoutBranch( 'master' )

    with open( fn, 'r' ) as fp:
        manifests.readFromFile( fp )


def read_mrgit_repo_map_file( repomap, baseurl, git ):
    ""
    git.checkoutBranch( REPO_MAP_BRANCH )

    try:
        with change_directory( git.getRootDir() ):
            repomap.readFromFile( baseurl )
    finally:
        git.checkoutBranch( 'master' )


def write_mrgit_repo_map_file( repomap, git ):
    ""
    with change_directory( git.getRootDir() ):

        if os.path.exists( REPOMAP_FILENAME ):
            repomap.writeToFile( REPOMAP_TEMPFILE )
            commit_repo_map_file_if_changed( git )

        else:
            repomap.writeToFile( REPOMAP_FILENAME )
            git.add( REPOMAP_FILENAME )
            git.commit( 'init '+REPOMAP_FILENAME )


def commit_repo_map_file_if_changed( git ):
    ""
    if filecmp.cmp( REPOMAP_FILENAME, REPOMAP_TEMPFILE ):
        os.remove( REPOMAP_TEMPFILE )
    else:
        os.rename( REPOMAP_TEMPFILE, REPOMAP_FILENAME )
        git.add( REPOMAP_FILENAME )
        git.commit( 'changed '+REPOMAP_FILENAME )


def print3( *args ):
    ""
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
