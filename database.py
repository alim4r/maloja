from bottle import Bottle, route, get, post, run, template, static_file, request, response, FormsDict
from importlib.machinery import SourceFileLoader
import urllib
import waitress
import os
import datetime
from cleanup import *
from utilities import *
import sys

dbserver = Bottle()


SCROBBLES = []	# Format: tuple(track_ref,timestamp,saved)
ARTISTS = []	# Format: artist
TRACKS = []	# Format: tuple(frozenset(artist_ref,...),title)

timestamps = set()

cla = CleanerAgent()
coa = CollectorAgent()
clients = []

lastsync = 0

rulescheck = ""



### symmetric keys are fine for now since we hopefully use HTTPS
def loadAPIkeys():
	global clients
	createTSV("clients/authenticated_machines.tsv")
	clients = parseTSV("clients/authenticated_machines.tsv","string","string")

def checkAPIkey(k):
	return (k in [k for [k,d] in clients])


####
## Getting dict representations of database objects
####

def getScrobbleObject(o):
	track = getTrackObject(TRACKS[o[0]])
	return {"artists":track["artists"],"title":track["title"],"time":o[1]}
	
def getArtistObject(o):
	return o
	
def getTrackObject(o):
	artists = [getArtistObject(ARTISTS[a]) for a in o[0]]
	return {"artists":artists,"title":o[1]}


####
## Creating or finding existing database entries
####


	
def createScrobble(artists,title,time):
	while (time in timestamps):
		time += 1
	timestamps.add(time)
	i = getTrackID(artists,title)
	obj = (i,time,False)
	SCROBBLES.append(obj)


def readScrobble(artists,title,time):
	while (time in timestamps):
		time += 1
	timestamps.add(time)
	i = getTrackID(artists,title)
	obj = (i,time,True)
	SCROBBLES.append(obj)
	

def getArtistID(name):

	obj = name
	try:
		i = ARTISTS.index(obj)
	except:
		i = len(ARTISTS)
		ARTISTS.append(obj)
	return i
			
def getTrackID(artists,title):
	artistset = set()
	for a in artists:
		artistset.add(getArtistID(name=a))
	obj = (frozenset(artistset),title)
	
	try:
		i = TRACKS.index(obj)
	except:
		i = len(TRACKS)
		TRACKS.append(obj)
	return i


####
## HTTP requests
####

@dbserver.route("/test")
def test_server():
	apikey = request.query.get("key")
	response.set_header("Access-Control-Allow-Origin","*")
	if not (checkAPIkey(apikey)):
		response.status = 403
		return "Wrong or Missing API key"
	
	else:
		response.status = 204
		return

@dbserver.route("/scrobbles")
def get_scrobbles():
	keys = FormsDict.decode(request.query)
	r = db_query(artist=keys.get("artist"),track=keys.get("track"),since=keys.get("since"),to=keys.get("to"))
	r.reverse()

	return {"list":r} ##json can't be a list apparently???

@dbserver.route("/tracks")
def get_tracks():
	keys = FormsDict.decode(request.query)
	artist = keys.get("artist")
	
	if artist is not None:
		artistid = ARTISTS.index(artist)
	
	# Option 1
	ls = [getTrackObject(t) for t in TRACKS if (artistid in t[0]) or (artistid==None)]
	
	# Option 2 is a bit more elegant but much slower
	#tracklist = [getTrackObject(t) for t in TRACKS]
	#ls = [t for t in tracklist if (artist in t["artists"]) or (artist==None)]
	
	return {"list":ls}
	
@dbserver.route("/artists")
def get_artists():
	
	return {"list":ARTISTS}
	
@dbserver.route("/charts/artists")
def get_charts_artists():
	since = request.query.get("since")
	to = request.query.get("to")
	
	return {"list":db_aggregate(by="ARTIST",since=since,to=to)}
	
@dbserver.route("/charts/tracks")
def get_charts_tracks():
	since = request.query.get("since")
	to = request.query.get("to")
	
	return {"list":db_aggregate(by="TRACK",since=since,to=to)}
	
@dbserver.route("/charts")
def get_charts():
	since = request.query.get("since")
	to = request.query.get("to")
	
	return {"number":db_aggregate(since=since,to=to)}
	
@dbserver.route("/pulse")
def get_pulse():
	since = request.query.get("since")
	to = request.query.get("to")
	(ts_start,ts_end) = getTimestamps(since,to)
	step = request.query.get("step","month")	
	trail = int(request.query.get("trail",3))
	
	[step,stepn] = (step.split("-") + [1])[:2]	# makes the multiplier 1 if not assigned
	stepn = int(stepn)
	
	d_start = getStartOf(ts_start,step)
	d_end = getStartOf(ts_end,step)
	
	d_start = getNext(d_start,step,stepn)			# first range should end right after the first active scrobbling week / month / whatever relevant step
	d_start = getNext(d_start,step,stepn * trail * -1)	# go one range back to begin

	results = []
	
	d_current = d_start
	while True:
		d_current_end = getNext(d_current,step,stepn * trail)
		#print("Checking from " + str(d_current[0]) + "-" + str(d_current[1]) + "-" + str(d_current[2]) + " to " + str(d_current_end[0]) + "-" + str(d_current_end[1]) + "-" + str(d_current_end[2]))
		res = db_aggregate(since=d_current,to=d_current_end)
		results.append({"from":d_current,"to":d_current_end,"scrobbles":res})
		d_current = getNext(d_current,step,stepn)
		if isPast(d_current_end,d_end):
			break
	
	return {"list":results}
		
	
@dbserver.route("/top/artists")
def get_top_artists():
	since = request.query.get("since")
	to = request.query.get("to")
	(ts_start,ts_end) = getTimestamps(since,to)
	step = request.query.get("step","month")	
	trail = int(request.query.get("trail",3))
	
	[step,stepn] = (step.split("-") + [1])[:2]	# makes the multiplier 1 if not assigned
	stepn = int(stepn)
	
	d_start = getStartOf(ts_start,step)
	d_end = getStartOf(ts_end,step)
	
	d_start = getNext(d_start,step,stepn)			# first range should end right after the first active scrobbling week / month / whatever relevant step
	d_start = getNext(d_start,step,stepn * trail * -1)	# go one range back to begin

	results = []
	
	d_current = d_start
	while True:
		d_current_end = getNext(d_current,step,stepn * trail)
		#print("Checking from " + str(d_current[0]) + "-" + str(d_current[1]) + "-" + str(d_current[2]) + " to " + str(d_current_end[0]) + "-" + str(d_current_end[1]) + "-" + str(d_current_end[2]))
		try:
			res = db_aggregate(since=d_current,to=d_current_end,by="ARTIST")[0]
			results.append({"from":d_current,"to":d_current_end,"artist":res["artist"],"scrobbles":res["scrobbles"]})
		except:
			results.append({"from":d_current,"to":d_current_end,"artist":None,"scrobbles":0})
		d_current = getNext(d_current,step,stepn)
		if isPast(d_current_end,d_end):
			break
	
	return {"list":results}
	
@dbserver.route("/top/tracks")
def get_top_tracks():
	since = request.query.get("since")
	to = request.query.get("to")
	(ts_start,ts_end) = getTimestamps(since,to)
	step = request.query.get("step","month")	
	trail = int(request.query.get("trail",3))
	
	[step,stepn] = (step.split("-") + [1])[:2]	# makes the multiplier 1 if not assigned
	stepn = int(stepn)
	
	d_start = getStartOf(ts_start,step)
	d_end = getStartOf(ts_end,step)
	
	d_start = getNext(d_start,step,stepn)			# first range should end right after the first active scrobbling week / month / whatever relevant step
	d_start = getNext(d_start,step,stepn * trail * -1)	# go one range back to begin

	results = []
	
	d_current = d_start
	while True:
		d_current_end = getNext(d_current,step,stepn * trail)
		#print("Checking from " + str(d_current[0]) + "-" + str(d_current[1]) + "-" + str(d_current[2]) + " to " + str(d_current_end[0]) + "-" + str(d_current_end[1]) + "-" + str(d_current_end[2]))
		try:
			res = db_aggregate(since=d_current,to=d_current_end,by="TRACK")[0]
			results.append({"from":d_current,"to":d_current_end,"track":res["track"],"scrobbles":res["scrobbles"]})
		except:
			results.append({"from":d_current,"to":d_current_end,"track":None,"scrobbles":0})
		d_current = getNext(d_current,step,stepn)
		if isPast(d_current_end,d_end):
			break
	
	return {"list":results}


def getStartOf(timestamp,unit):
	date = datetime.datetime.utcfromtimestamp(timestamp)
	if unit == "year":
		return [date.year,1,1]
	elif unit == "month":
		return [date.year,date.month,1]
	elif unit == "day":
		return [date.year,date.month,date.day]
	elif unit == "week":
		change = (date.weekday() + 1) % 7
		d = datetime.timedelta(days=change)
		newdate = date - d
		return [newdate.year,newdate.month,newdate.day]
		
def getNext(time,unit,step=1):
	if unit == "year":
		return [time[0] + step,time[1],time[2]]
	elif unit == "month":
		result = [time[0],time[1] + step,time[2]]
		while result[1] > 12:
			result[1] -= 12
			result[0] += 1
		while result[1] < 1:
			result[1] += 12
			result[0] -= 1
		return result
	elif unit == "day":
		dt = datetime.datetime(time[0],time[1],time[2])
		d = datetime.timedelta(days=step)
		newdate = dt + d
		return [newdate.year,newdate.month,newdate.day]
		#eugh
	elif unit == "week":
		return getNext(time,"day",step * 7)
		
@dbserver.route("/artistinfo")	
def artistInfo():
	keys = FormsDict.decode(request.query)
	artist = keys.get("artist")
	
	charts = db_aggregate(by="ARTIST")
	scrobbles = len(db_query(artist=artist)) #we cant take the scrobble number from the charts because that includes all countas scrobbles
	try:
		c = [e for e in charts if e["artist"] == artist][0]
		others = coa.getAllAssociated(artist)
		return {"scrobbles":scrobbles,"position":charts.index(c) + 1,"associated":others}
	except:
		# if the artist isnt in the charts, they are not being credited and we need to show information about the credited one
		artist = coa.getCredited(artist)
		c = [e for e in charts if e["artist"] == artist][0]
		return {"replace":artist,"scrobbles":scrobbles,"position":charts.index(c) + 1}
	
def isPast(date,limit):
	if not date[0] == limit[0]:
		return date[0] > limit[0]
	if not date[1] == limit[1]:
		return date[1] > limit[1]
	return (date[2] > limit[2])

@dbserver.get("/newscrobble")
def pseudo_post_scrobble():
	keys = FormsDict.decode(request.query) # The Dal★Shabet handler
	artists = keys.get("artist")
	title = keys.get("title")
	try:
		time = int(keys.get("time"))
	except:
		time = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
	(artists,title) = cla.fullclean(artists,title)

	## this is necessary for localhost testing
	response.set_header("Access-Control-Allow-Origin","*")
	
	createScrobble(artists,title,time)
	
	if (time - lastsync) > 3600:
		sync()
	
	return ""
	
@dbserver.post("/newscrobble")
def post_scrobble():
	keys = FormsDict.decode(request.forms) # The Dal★Shabet handler
	artists = keys.get("artist")
	title = keys.get("title")
	apikey = keys.get("key")
	if not (checkAPIkey(apikey)):
		response.status = 403
		return ""
	
	try:
		time = int(keys.get("time"))
	except:
		time = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
	(artists,title) = cla.fullclean(artists,title)

	## this is necessary for localhost testing
	response.set_header("Access-Control-Allow-Origin","*")
	
	createScrobble(artists,title,time)
	
	if (time - lastsync) > 3600:
		sync()
	
	return ""
	
@dbserver.route("/sync")
def abouttoshutdown():
	sync()
	#sys.exit()

@dbserver.post("/newrule")
def newrule():
	keys = FormsDict.decode(request.forms)
	addEntry("rules/webmade.tsv",[k for k in keys])
	
@dbserver.route("/issues")
def issues():
	combined = []
	duplicates = []
	newartists = []
	
	
	import itertools
	import difflib
	
	sortedartists = ARTISTS.copy()
	sortedartists.sort(key=len,reverse=True)
	reversesortedartists = sortedartists.copy()
	reversesortedartists.reverse()
	for a in reversesortedartists:
		
		nochange = cla.confirmedReal(a)
		
		st = a
		lis = []
		reachedmyself = False
		for ar in sortedartists:
			if (ar != a) and not reachedmyself:
				continue
			elif not reachedmyself:
				reachedmyself = True
				continue
			
			if (ar.lower() == a.lower()) or ("the " + ar.lower() == a.lower()) or ("a " + ar.lower() == a.lower()):
				duplicates.append((ar,a))
				break
		
			if (ar + " " in st) or (" " + ar in st):
				lis.append(ar)
				st = st.replace(ar,"").strip()
			elif (ar == st):
				lis.append(ar)
				st = ""
				if not nochange:
					combined.append((a,lis))
				break
				
			elif (ar in st) and len(ar)*2 > len(st):
				duplicates.append((a,ar))
		
		st = st.replace("&","").replace("and","").replace("with","").strip()
		if st != "" and st != a:
			if len(st) < 5 and len(lis) == 1:
				#check if we havent just randomly found the string in another word
				#if (" " + st + " ") in lis[0] or (lis[0].endswith(" " + st)) or (lis[0].startswith(st + " ")):
				duplicates.append((a,lis[0]))
			elif len(st) < 5 and len(lis) > 1 and not nochange:
				combined.append((a,lis))
			elif len(st) >= 5 and not nochange:
				#check if we havent just randomly found the string in another word
				if (" " + st + " ") in a or (a.endswith(" " + st)) or (a.startswith(st + " ")):
					newartists.append((st,a,lis))
	
	#for c in itertools.combinations(ARTISTS,3):
	#	l = list(c)
	#	print(l)
	#	l.sort(key=len,reverse=True)
	#	[full,a1,a2] = l
	#	if (a1 + " " + a2 in full) or (a2 + " " + a1 in full):
	#		combined.append((full,a1,a2))


	#for c in itertools.combinations(ARTISTS,2):
	#	if
	#
	#	if (c[0].lower == c[1].lower):
	#		duplicates.append((c[0],c[1]))
			
			
	#	elif (c[0] + " " in c[1]) or (" " + c[0] in c[1]) or (c[1] + " " in c[0]) or (" " + c[1] in c[0]):
	#		if (c[0] in c[1]):
	#			full, part = c[1],c[0]
	#			rest = c[1].replace(c[0],"").strip()
	#		else:
	#			full, part = c[0],c[1]
	#			rest = c[0].replace(c[1],"").strip()
	#		if rest in ARTISTS and full not in [c[0] for c in combined]:
	#			combined.append((full,part,rest))
	
	#	elif (c[0] in c[1]) or (c[1] in c[0]):
	#		duplicates.append((c[0],c[1]))
			
	
	return {"duplicates":duplicates,"combined":combined,"newartists":newartists}


	
####
## Server operation
####



# Starts the server
def runserver(PORT):
	global lastsync
	lastsync = time = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
	build_db()
	coa.updateIDs(ARTISTS)

	loadAPIkeys()

	run(dbserver, host='0.0.0.0', port=PORT, server='waitress')


def build_db():
	
	global rulescheck
	
	
	global SCROBBLES
	
	SCROBBLESNEW = []
	for t in SCROBBLES:
		if not t[2]:
			SCROBBLESNEW.append(t)

	SCROBBLES = SCROBBLESNEW
	
	for f in os.listdir("scrobbles/"):
		
		if not (f.endswith(".tsv")):
			continue
		
		logfile = open("scrobbles/" + f)
		for l in logfile:
			
			l = l.replace("\n","")
			data = l.split("\t")
			
			## saving album in the scrobbles is supported, but for now we don't use it. It shouldn't be a defining part of the track (same song from Album or EP), but derived information
			artists = data[1].split("␟")
			#album = data[3]
			title = data[2]
			time = int(data[0])
			
			readScrobble(artists,title,time)
			
	SCROBBLES.sort(key = lambda tup: tup[1])
			
	
	
		


# Saves all cached entries to disk			
def sync():
	for idx in range(len(SCROBBLES)):
		if not SCROBBLES[idx][2]:
			
			t = getScrobbleObject(SCROBBLES[idx])
			
			artistss = "␟".join(t["artists"])
			timestamp = datetime.date.fromtimestamp(t["time"])
			
			entry = "\t".join([str(t["time"]),artistss,t["title"]])
		
			monthfile = open("scrobbles/" + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv","a")
			monthfile.write(entry)
			monthfile.write("\n")
			monthfile.close()
			
			if os.path.exists("scrobbles/" + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv.rulestate"):
				checkfile = open("scrobbles/" + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv.rulestate","r")
				print("Checking rulestate of " + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv")
				if checkfile.read() != cla.checksums:
					print("Checksum does not match, file is inconsistent")
					#cla.checksums represents the rule state that all current unsaved scrobbles were created under. if this is the same than the existing one, we're all good
					#if not, the file is not consistent to any single rule state
					checkfile.close()
					checkfile = open("scrobbles/" + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv.rulestate","w")
					checkfile.write("INVALID") # this will never match any sha256sum
				checkfile.close()
			else:
				print(str(timestamp.year) + "_" + str(timestamp.month) + ".tsv does not yet exist, writing current rulestate")
				#if the file didn't exist before, all its scrobbles come from our current server instance and are therefore under the current rule state
				checkfile = open("scrobbles/" + str(timestamp.year) + "_" + str(timestamp.month) + ".tsv.rulestate","w")
				checkfile.write(cla.checksums)
				checkfile.close()
			
			SCROBBLES[idx] = (SCROBBLES[idx][0],SCROBBLES[idx][1],True)
			
	global lastsync
	lastsync = time = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
	print("Database saved to disk.")
			




####
## Database queries
####



# Queries the database			
def db_query(artist=None,track=None,since=None,to=None):
	(since, to) = getTimestamps(since,to)
	
	
	# this is not meant as a search function. we *can* query the db with a string, but it only works if it matches exactly (and title string simply picks the first track with that name)	
	if isinstance(artist, str):
		artist = ARTISTS.index(artist)
	if isinstance(track, str):
		track = TRACKS.index(track)
	
	return [getScrobbleObject(s) for s in SCROBBLES if (s[0] == track or track==None) and (artist in TRACKS[s[0]][0] or artist==None) and (since < s[1] < to)]
	# pointless to check for artist when track is checked because every track has a fixed set of artists, but it's more elegant this way

		
	#thingsweneed = ["artists","title","time"]
	#return [{key:t[key] for key in thingsweneed} for t in DATABASE if (artist in t["artists"] or artist==None) and (t["title"]==title or title==None) and (since < t["time"] < to)]
	

# Queries that... well... aggregate
def db_aggregate(by=None,since=None,to=None):
	(since, to) = getTimestamps(since,to)
	
	if (by=="ARTIST"):
		#this is probably a really bad idea
		#for a in ARTISTS:
		#	num = len(db_query(artist=a,since=since,to=to))
		#	
				
		# alright let's try for real
		charts = {}
		for s in [scr for scr in SCROBBLES if since < scr[1] < to]:
			artists = TRACKS[s[0]][0]
			for a in coa.getCreditedList(artists):
				# this either creates the new entry or increments the existing one
				charts[a] = charts.setdefault(a,0) + 1
				
		ls = [{"artist":getArtistObject(ARTISTS[a]),"scrobbles":charts[a]} for a in charts]
		return sorted(ls,key=lambda k:k["scrobbles"], reverse=True)
		
	elif (by=="TRACK"):
		charts = {}
		for s in [scr for scr in SCROBBLES if since < scr[1] < to]:
			track = s[0]
			# this either creates the new entry or increments the existing one
			charts[track] = charts.setdefault(track,0) + 1
				
		ls = [{"track":getTrackObject(TRACKS[t]),"scrobbles":charts[t]} for t in charts]
		return sorted(ls,key=lambda k:k["scrobbles"], reverse=True)
		
	else:
		return len([scr for scr in SCROBBLES if since < scr[1] < to])
	


# Search for strings
def db_search(query,type=None):
	if type=="ARTIST":
		results = []
		for a in ARTISTS:
			if query.lower() in a.lower():
				results.append(a)
	
	if type=="TRACK":
		results = []
		for t in TRACKS:
			if query.lower() in t[1].lower():
				results.append(t)
	
	return results


####
## Useful functions
####


# Takes user inputs like YYYY/MM and returns the timestamps. Returns timestamp if timestamp was already given.	
def getTimestamps(f,t):
	#(f,t) = inp
	if isinstance(f, str):
		f = [int(x) for x in f.split("/")]
		
	if isinstance(t, str):
		t = [int(x) for x in t.split("/")]
		
	
	# this step is done if either the input is a list or the first step was done (which creates a list)	
	if isinstance(f, list):
		date = [1970,1,1,0,0]
		date[:len(f)] = f
		f = int(datetime.datetime(date[0],date[1],date[2],date[3],date[4],tzinfo=datetime.timezone.utc).timestamp())
		
	if isinstance(t, list):
		date = [1970,1,1,0,0]
		date[:len(t)] = t
		t = int(datetime.datetime(date[0],date[1],date[2],date[3],date[4],tzinfo=datetime.timezone.utc).timestamp())
		
		
	if (f==None):
		f = min(timestamps)
	if (t==None):
		t = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).timestamp()
	
	return (f,t)
	

	
def getArtistId(nameorid):
	if isinstance(nameorid,int):
		return nameorid
	else:
		try:
			return ARTISTS.index(nameorid)
		except:
			return -1
			
			
