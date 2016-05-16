#-*- encoding=utf-8 -*-

import urllib
import urllib2
import re
from bs4 import BeautifulSoup
from urlparse import urljoin
import sqlite3 as sqlite
from ConfigParser import ConfigParser
import sys
reload(sys)
sys.setdefaultencoding('utf-8')


class crawler:
    def __init__(self,dbname):
        self.con = sqlite.connect(dbname)


    def __del__(self):
        self.con.close()

    def dbcommit(self):
        self.con.commit()

    #support function, to get id of item, if item doesn't exist, add to DB
    def getentryid(self,table,field,value,createnew=True):
        cur = self.con.execute("select rowid from %s where %s='%s'" % (table,field,value))
        res = cur.fetchone()
        if res == None:

            cur = self.con.execute("insert into %s (%s) values ('%s')" % (table,field,value))
            return cur.lastrowid

        else:
            return res[0]

    #build index for every page
    def addtoindex(self,url,soup):
        if self.isindexed(url):return
        print 'Indexing '+url

        text = self.gettextonly(soup)
        words = self.separatewords(text)

        urlid = self.getentryid('urllist','url',url)

        for i in range(len(words)):
            word = words[i]
            #if word in ignorewords: continue

            wordid = self.getentryid('wordlist','word',word)
            self.con.execute("insert into wordlocation (urlid,wordid,location) \
              values (%d,%d,%d)" % (urlid,wordid,i))

    # get words from one HTML webpage
    def gettextonly(self,soup):
        v = soup.string
        if v == None:
            c=soup.contents
            resulttext = ''
            for t in c:
                subtext = self.gettextonly(t)
                resulttext +=subtext+'\n'
            return resulttext
        else:
            return v.strip()

    #separate words with blank
    def separatewords(self,text):
        splitter = re.compile('\\W*')
        return [s.lower() for s in splitter.split(text) if s != '']

    #if url in indexed ,return True
    def isindexed(self,url):
        u = self.con.execute("select rowid from urllist where url = '%s'" % url).fetchone()

        if(u != None):
            v = self.con.execute("select * from wordlocation where urlid = %d" % u[0]).fetchone()
            if v != None: return True

        return False

    # add linker to link 2 url
    def addlinkref(self,urlFrom, urlTo, linkText):

        urlFromid = self.getentryid('urllist','url',urlFrom)
        urlToid = self.getentryid('urllist','url',urlTo)
        self.con.execute('insert into link (fromid,toid) values (%d,%d)' % (urlFromid,urlToid))
        words = self.separatewords(linkText)


        for i in range(len(words)):
            word = words[i]
            # if word in ignorewords: continue

            wordid = self.getentryid('wordlist', 'word', word)
            self.con.execute('insert into linkwords (wordid,linkid) values (%d,%d)' % (wordid,urlToid))




    # create index of tables
    def createindextables(self):
        self.con.execute('create table urllist(url)')
        self.con.execute('create table wordlist(word)')
        self.con.execute('create table wordlocation(urlid,wordid,location)')
        self.con.execute('create table link(fromid integer,toid integer)')
        self.con.execute('create table linkwords(wordid,linkid)')

        self.con.execute('create index wordidx on wordlist(word)')
        self.con.execute('create index urlidx on urllist(url)')
        self.con.execute('create index wordurlidx on wordlocation(wordid)')
        self.con.execute('create index urltoidx on link(toid)')
        self.con.execute('create index urlfromidx on link(fromid)')
        self.dbcommit()


    def gethost(self,page):
        proto,rest = urllib.splittype(page)
        host,rest = urllib.splithost(rest)
        return host
    # from one page to search to depth
    def crawl(self,pages,depth=2):

        conf = ConfigParser()
        conf.read('conf.ini')
        for i in range(depth):
            newpages = set()

            for page in pages:
                try :
                    headers = dict(conf.items('header'))

                    headers['Host'] = self.gethost(page)
                    request = urllib2.Request(page,headers=headers)
                    c = urllib2.urlopen(request)

                except:
                    print "Could not open %s" % page
                    continue

                # print c.read()
                soup = BeautifulSoup(c.read())
                self.addtoindex(page,soup)

                links = soup('a')
                for link in links:
                    if ('href' in dict(link.attrs)):
                        url = urljoin(page,link['href'])

                        #if url.find("'")!=-1: continue

                        url = url.split("#")[0]

                        if url[0:4] =='http' and not self.isindexed(url):
                            newpages.add(url)

                        linkText = self.gettextonly(link)
                        self.addlinkref(page,url,linkText)

                self.dbcommit()

            print 'depth is '+str(i)
            pages = newpages

    def calculatepagerank(self,iterations=20):

        self.con.execute('drop table if exists pagerank')
        self.con.execute('create table pagerank(urlid primary key,score)')

        self.con.execute('insert into pagerank select rowid, 1.0 from urllist')
        self.dbcommit()

        for i in range(iterations):
            print 'Iteration %d' % (i)
            for (urlid,) in self.con.execute('select rowid from urllist'):
                pr = 0.15

                for linker in self.con.execute('select distinct fromid from link where toid=%d' %urlid):

                    linkingpr = self.con.execute('select score from pagerank where urlid=%d' % linker).fetchone()[0]

                    linkingcount = self.con.execute(
                        'select count(*) from link where fromid=%d' % linker
                    ).fetchone()[0]
                    pr+=0.85*(linkingpr/linkingcount)

                self.con.execute(
                    'update pagerank set score=%f where urlid=%d' %(pr,urlid)
                )

            self.dbcommit()



class searcher:
    def __init__(self,dbname):
        self.con = sqlite.connect(dbname)

    def __del__(self):
        self.con.close()

    def getmatchrows(self,q):

        fieldlist = 'w0.urlid'
        tablelist = ''
        clauselist = ''
        wordids = []

        # split words with blank
        words = q.split(" ")
        tablenumber = 0

        for word in words:

            wordrow = self.con.execute("select rowid from wordlist where word = '%s'" % word).fetchone()

            if wordrow != None:
                wordid = wordrow[0]
                wordids.append(wordid)
                if tablenumber >0:
                    tablelist += ','
                    clauselist += ' and '
                    clauselist += 'w%d.urlid=w%d.urlid and ' % (tablenumber-1,tablenumber)
                fieldlist+=',w%d.location' % tablenumber
                tablelist+='wordlocation w%d' % tablenumber
                clauselist+='w%d.wordid=%d' % (tablenumber,wordid)
                tablenumber+=1
            else:
                print '"%s" is not in the wordlist, please try other words' % word
                return False

        fullquery = 'select %s from %s where %s' % (fieldlist,tablelist,clauselist)
        cur = self.con.execute(fullquery)
        rows = [row for row in cur]

        return rows,wordids

    def getscoredlist(self,rows,wordids):
        totalscores=dict([(row[0],0) for row in rows])

        weights = [(1.0,self.pagerankscore(rows))]

        for (weight, scores) in weights:
            for url in totalscores:
                totalscores[url] += weight*scores[url]
        return totalscores

    def geturlname(self,id):
        return self.con.execute("select url from urllist where rowid=%d" % id).fetchone()[0]

    def query(self,q):

        rows,wordids = self.getmatchrows(q)
        scores = self.getscoredlist(rows,wordids)
        rankedscores = sorted([(score,url) for (url,score) in scores.items()],reverse=1)
        for (score,urlid) in rankedscores[0:10]:
            print '%f\t%s' % (score,self.geturlname(urlid))

    def normalizescores(self,scores,smallIsBetter=0):
        vsmall = 0.00001
        if smallIsBetter:
            minscore = min(scores.values())
            return dict([(u,float(minscore)/max(vsmall,l)) for (u,l) in scores.items()])
        else:
            maxscore = max(scores.values())
            if maxscore == 0: maxscore = vsmall
            return dict([(u,float(c)/maxscore) for (u,c) in scores.items()])

    def frequencyscore(self,rows):
        counts = dict([(row[0],0) for row in rows])
        print 'initial counts'
        for row in rows: counts[row[0]] += 1
        return self.normalizescores(counts)

    def locationscore(self,rows):
        locations = dict([(row[0],1000000) for row in rows])
        for row in rows:
            loc = sum(row[1:])
            if loc<locations[row[0]]:locations[row[0]] = loc

        return self.normalizescores(locations,smallIsBetter=1)

    def distancescore(self,rows):
        if len(rows[0]) <=2: return dict([(row[0],1.0) for row in rows])

        mindistance = dict([(row[0],1000000) for row in rows])

        for row in rows:
            dist = sum([abs(row[i]-row[i-1]) for i in range(2,len(row))])
            if dist < mindistance[row[0]]: mindistance[row[0]]=dist

        return self.normalizescores(mindistance,smallIsBetter=1)

    def pagerankscore(self,rows):
        pageranks = dict([(row[0],self.con.execute('select score from pagerank \
where urlid=%d' % row[0]).fetchone()[0])for row in rows])
        maxrank = max(pageranks.values())

        normalizedscores = dict([(u,float(l)/maxrank) for (u,l) in pageranks.items()])
        return normalizedscores






# if __name__ == '__main__':
#     print 'searchengin is working'
#     pagelist = ['http://www.baidu.com']
#     crawler = crawler('text.db')
#     crawler.createindextables()
#     crawler.crawl(pagelist)
#     crawler.calculatepagerank()

    #e = searcher('text.db')



